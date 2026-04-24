#!/usr/bin/env python3
"""Run per-stage Fireworks model comparisons against saved pipeline artifacts.

This script replays one LLM-backed stage at a time from an existing
``output/artifacts/YYYY-MM-DD`` fixture, swapping in a matrix of candidate
Fireworks models. It generates JSON and HTML reports similar in spirit to the
existing analyze-domain comparison artifact, but generalized across stages.

The default model set targets the major Fireworks serverless text models that
are relevant to this pipeline as of 2026-04-23.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import dataclass
import html
import importlib
import json
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline as pipeline_module
from morning_digest.config import load_config
from morning_digest import llm as llm_module

log = logging.getLogger(__name__)

DEFAULT_STAGE_ORDER = (
    "enrich_articles",
    "compress",
    "analyze_domain",
    "prepare_spiritual_weekly",
    "prepare_spiritual",
    "seams",
    "cross_domain",
    "coverage_gaps",
)


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    provider: str
    model: str
    max_tokens: int
    temperature: float | None
    input_per_m: float
    output_per_m: float
    notes: str = ""

    def as_config(self) -> dict[str, Any]:
        cfg = {
            "provider": self.provider,
            "model": self.model,
            "max_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            cfg["temperature"] = self.temperature
        return cfg


# TODO: Move benchmark model registry into a dedicated benchmark config file
# (separate from runtime pipeline config) before the next comparison cycle.
MODEL_SPECS: OrderedDict[str, ModelSpec] = OrderedDict(
    [
        (
            "kimi_k2_6",
            ModelSpec(
                key="kimi_k2_6",
                label="Kimi K2.6",
                provider="fireworks",
                model="accounts/fireworks/models/kimi-k2p6",
                max_tokens=16000,
                temperature=0.3,
                input_per_m=0.95,
                output_per_m=4.00,
                notes="Current Fireworks 'new' flagship; highest price in this pool.",
            ),
        ),
        (
            "minimax_m2_7",
            ModelSpec(
                key="minimax_m2_7",
                label="MiniMax M2.7",
                provider="fireworks",
                model="accounts/fireworks/models/minimax-m2p7",
                max_tokens=16000,
                temperature=0.3,
                input_per_m=0.30,
                output_per_m=1.20,
                notes="Current pipeline default for most stages.",
            ),
        ),
        (
            "qwen3_6_plus",
            ModelSpec(
                key="qwen3_6_plus",
                label="Qwen3.6 Plus",
                provider="fireworks",
                model="accounts/fireworks/models/qwen3p6-plus",
                max_tokens=16000,
                temperature=0.3,
                input_per_m=0.50,
                output_per_m=3.00,
                notes="New Fireworks model; vision-capable but usable for text-only stages.",
            ),
        ),
        (
            "glm_5_1",
            ModelSpec(
                key="glm_5_1",
                label="GLM 5.1",
                provider="fireworks",
                model="accounts/fireworks/models/glm-5p1",
                max_tokens=16000,
                temperature=0.3,
                input_per_m=1.40,
                output_per_m=4.40,
                notes="New Fireworks model; expensive enough to justify explicit evaluation.",
            ),
        ),
        (
            "deepseek_v3_2",
            ModelSpec(
                key="deepseek_v3_2",
                label="DeepSeek v3.2",
                provider="fireworks",
                model="accounts/fireworks/models/deepseek-v3p2",
                max_tokens=16000,
                temperature=0.3,
                input_per_m=0.56,
                output_per_m=1.68,
                notes="Strong cost/performance baseline available on Fireworks today.",
            ),
        ),
        (
            "glm_5",
            ModelSpec(
                key="glm_5",
                label="GLM-5",
                provider="fireworks",
                model="accounts/fireworks/models/glm-5",
                max_tokens=16000,
                temperature=0.3,
                input_per_m=1.00,
                output_per_m=3.20,
                notes="Prior GLM release still listed on Fireworks serverless.",
            ),
        ),
        (
            "kimi_k2_5",
            ModelSpec(
                key="kimi_k2_5",
                label="Kimi K2.5",
                provider="fireworks",
                model="accounts/fireworks/models/kimi-k2p5",
                max_tokens=16000,
                temperature=0.3,
                input_per_m=0.60,
                output_per_m=3.00,
                notes="Existing Kimi baseline already used in seams.",
            ),
        ),
    ]
)

MODEL_GROUPS = {
    "major": (
        "kimi_k2_6",
        "minimax_m2_7",
        "qwen3_6_plus",
        "glm_5_1",
        "deepseek_v3_2",
        "glm_5",
        "kimi_k2_5",
    ),
    "new": (
        "kimi_k2_6",
        "minimax_m2_7",
        "qwen3_6_plus",
        "glm_5_1",
    ),
}


@dataclass
class TraceRecord:
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    elapsed_s: float
    json_mode: bool
    stream: bool
    ok: bool
    error: str = ""


class TracedLLM:
    def __init__(self, base_call: Callable[..., Any]):
        self._base_call = base_call
        self._lock = threading.Lock()
        self.records: list[TraceRecord] = []

    def __call__(
        self,
        system_prompt: str,
        user_content: str,
        model_config: dict,
        max_retries: int = 2,
        json_mode: bool = True,
        stream: bool = True,
    ) -> dict | str:
        model = str((model_config or {}).get("model", ""))
        provider = str((model_config or {}).get("provider", ""))
        input_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(user_content)
        t_start = time.monotonic()
        try:
            result = self._base_call(
                system_prompt,
                user_content,
                model_config,
                max_retries=max_retries,
                json_mode=json_mode,
                stream=stream,
            )
        except Exception as exc:
            elapsed = time.monotonic() - t_start
            record = TraceRecord(
                model=model,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=0,
                elapsed_s=elapsed,
                json_mode=json_mode,
                stream=stream,
                ok=False,
                error=str(exc),
            )
            with self._lock:
                self.records.append(record)
            raise

        elapsed = time.monotonic() - t_start
        output_tokens = _estimate_tokens(_serialize_for_tokens(result))
        record = TraceRecord(
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_s=elapsed,
            json_mode=json_mode,
            stream=stream,
            ok=True,
        )
        with self._lock:
            self.records.append(record)
        return result


def comparable_stage_names(config: dict) -> list[str]:
    manifest_names = [stage["name"] for stage in config.get("pipeline", {}).get("stages", [])]
    return [name for name in DEFAULT_STAGE_ORDER if name in manifest_names]


def resolve_model_keys(group_or_csv: str) -> list[str]:
    if group_or_csv in MODEL_GROUPS:
        return list(MODEL_GROUPS[group_or_csv])
    keys = [item.strip() for item in group_or_csv.split(",") if item.strip()]
    unknown = [key for key in keys if key not in MODEL_SPECS]
    if unknown:
        raise ValueError(f"Unknown model key(s): {', '.join(unknown)}")
    return keys


def _estimate_tokens(value: str | None) -> int:
    text = str(value or "")
    if not text:
        return 0
    return max(1, len(text) // 4)


def _serialize_for_tokens(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _artifact_dir(run_date: str) -> Path:
    return ROOT / "output" / "artifacts" / run_date


def load_stage_fixture(
    config: dict,
    run_date: str,
    stage_name: str,
) -> tuple[dict, dict, Path]:
    artifact_dir = _artifact_dir(run_date)
    if not artifact_dir.exists():
        raise FileNotFoundError(f"Artifact dir not found: {artifact_dir}")

    stage_manifest = config.get("pipeline", {}).get("stages", [])
    stage_cfg = next((item for item in stage_manifest if item["name"] == stage_name), None)
    if stage_cfg is None:
        raise ValueError(f"Stage not found in manifest: {stage_name}")

    context: dict[str, Any] = {}
    run_meta_path = artifact_dir / "run_meta.json"
    if run_meta_path.exists():
        context["run_meta"] = json.loads(run_meta_path.read_text(encoding="utf-8"))

    for prior_stage in stage_manifest:
        name = prior_stage["name"]
        if name == stage_name:
            break
        pipeline_module._load_cached_stage_outputs(name, context, artifact_dir)

    pipeline_module._run_stage_before_hook(
        stage_name,
        context,
        run_date=run_date,
        artifact_dir=artifact_dir,
        dry_run=True,
        load_dir=artifact_dir,
        config=config,
        stage_from=stage_name,
        from_plan=False,
    )
    return context, stage_cfg, artifact_dir


def load_reference_outputs(stage_name: str, artifact_dir: Path) -> dict[str, Any]:
    context: dict[str, Any] = {}
    pipeline_module._load_cached_stage_outputs(stage_name, context, artifact_dir)
    meta = pipeline_module._get_stage_meta(stage_name)
    return {key: deepcopy(context.get(key)) for key in meta["context_keys"] if key in context}


@contextmanager
def _patched_attr(module_name: str, attr_name: str, replacement: Any):
    module = importlib.import_module(module_name)
    if not hasattr(module, attr_name):
        yield
        return
    original = getattr(module, attr_name)
    setattr(module, attr_name, replacement)
    try:
        yield
    finally:
        setattr(module, attr_name, original)


@contextmanager
def patch_stage(stage_name: str, tracer: TracedLLM):
    with ExitStack() as stack:
        stack.enter_context(_patched_attr(f"stages.{stage_name}", "call_llm", tracer))
        if stage_name == "cross_domain":
            stack.enter_context(_patched_attr("cross_domain.stage", "call_llm", tracer))
            stack.enter_context(_patched_attr("stages.cross_domain", "call_llm", tracer))
        if stage_name == "prepare_spiritual_weekly":
            stack.enter_context(
                _patched_attr("stages.prepare_spiritual_weekly", "_load_existing", lambda _path: None)
            )
            stack.enter_context(
                _patched_attr("stages.prepare_spiritual_weekly", "_write_artifact", lambda _path, _artifact: None)
            )
        if stage_name == "coverage_gaps":
            stack.enter_context(
                _patched_attr("stages.coverage_gaps", "_append_history", lambda _result: None)
            )
        yield


def run_stage_once(
    config: dict,
    run_date: str,
    stage_name: str,
    model_spec: ModelSpec,
) -> dict[str, Any]:
    context, stage_cfg, artifact_dir = load_stage_fixture(config, run_date, stage_name)
    module = importlib.import_module(f"stages.{stage_name}")
    tracer = TracedLLM(llm_module.call_llm)
    model_config = _resolve_stage_candidate_model_config(
        config,
        stage_cfg,
        stage_name,
        model_spec,
    )
    start = time.monotonic()
    try:
        with patch_stage(stage_name, tracer):
            outputs = module.run(
                deepcopy(context),
                config,
                model_config,
                stage_cfg=deepcopy(stage_cfg),
                dry_run=True,
            )
        elapsed = time.monotonic() - start
        metrics = evaluate_stage_output(stage_name, outputs, context, tracer.records, model_spec)
        return {
            "stage": stage_name,
            "model_key": model_spec.key,
            "label": model_spec.label,
            "model_id": model_spec.model,
            "elapsed_s": elapsed,
            "traces": tracer.records,
            "metrics": metrics,
            "outputs": outputs,
            "artifact_dir": str(artifact_dir),
        }
    except Exception as exc:
        elapsed = time.monotonic() - start
        metrics = OrderedDict(
            [
                ("quality_score", 0),
                ("status", "error"),
                ("llm_calls", len(tracer.records)),
                ("est_cost_usd", _format_cost(_estimate_cost_usd(tracer.records, model_spec))),
            ]
        )
        return {
            "stage": stage_name,
            "model_key": model_spec.key,
            "label": model_spec.label,
            "model_id": model_spec.model,
            "elapsed_s": elapsed,
            "traces": tracer.records,
            "metrics": metrics,
            "error": str(exc),
            "artifact_dir": str(artifact_dir),
        }


def _resolve_stage_candidate_model_config(
    config: dict,
    stage_cfg: dict,
    stage_name: str,
    model_spec: ModelSpec,
) -> dict[str, Any]:
    """Swap only the model identity, preserving stage-specific tuning knobs.

    The comparison should answer "which model fits this stage best under the
    stage's normal token/temperature envelope?", not "what happens if every
    stage is forced through a single global token budget?".
    """
    base = pipeline_module._get_stage_model_config(
        stage_cfg,
        stage_name=stage_name,
        config=config,
    ) or {}
    resolved = deepcopy(base)
    resolved["provider"] = model_spec.provider
    resolved["model"] = model_spec.model
    if "max_tokens" not in resolved:
        resolved["max_tokens"] = model_spec.max_tokens
    if "temperature" not in resolved and model_spec.temperature is not None:
        resolved["temperature"] = model_spec.temperature
    return resolved


def _trace_summary(traces: list[TraceRecord], model_spec: ModelSpec) -> OrderedDict[str, Any]:
    input_tokens = sum(item.input_tokens for item in traces)
    output_tokens = sum(item.output_tokens for item in traces)
    cost_usd = _estimate_cost_usd(traces, model_spec) if model_spec else 0.0
    return OrderedDict(
        [
            ("llm_calls", len(traces)),
            ("input_k_tokens", round(input_tokens / 1000, 1)),
            ("output_k_tokens", round(output_tokens / 1000, 1)),
            ("est_cost_usd", _format_cost(cost_usd)),
        ]
    )


def _estimate_cost_usd(traces: list[TraceRecord], model_spec: ModelSpec | None) -> float:
    if model_spec is None:
        return 0.0
    input_tokens = sum(item.input_tokens for item in traces)
    output_tokens = sum(item.output_tokens for item in traces)
    return (
        (input_tokens / 1_000_000) * model_spec.input_per_m
        + (output_tokens / 1_000_000) * model_spec.output_per_m
    )


def _format_cost(value: float) -> str:
    return f"${value:.4f}"


def evaluate_stage_output(
    stage_name: str,
    outputs: dict[str, Any],
    context: dict[str, Any],
    traces: list[TraceRecord],
    model_spec: ModelSpec,
) -> OrderedDict[str, Any]:
    evaluator = _EVALUATORS.get(stage_name, _evaluate_generic)
    metrics = evaluator(outputs, context)
    summary = _trace_summary(traces, model_spec)
    merged = OrderedDict()
    quality = int(metrics.pop("quality_score", 0))
    merged["quality_score"] = quality
    merged["status"] = metrics.pop("status", "ok")
    merged.update(summary)
    merged.update(metrics)
    return merged


def _evaluate_generic(outputs: dict[str, Any], _context: dict[str, Any]) -> OrderedDict[str, Any]:
    score = 100 if outputs else 0
    return OrderedDict(
        [
            ("quality_score", score),
            ("status", "ok" if outputs else "empty"),
            ("top_level_keys", len(outputs)),
        ]
    )


def _evaluate_enrich_articles(outputs: dict[str, Any], context: dict[str, Any]) -> OrderedDict[str, Any]:
    records = ((outputs or {}).get("enrich_articles") or {}).get("records", []) or []
    enriched = ((outputs or {}).get("enriched_sources") or {}).get("rss", []) or []
    raw_items = ((context.get("raw_sources") or {}).get("rss") or [])
    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    changed = 0
    for before, after in zip(raw_items, enriched, strict=False):
        if str(before.get("summary", "")).strip() != str(after.get("summary", "")).strip():
            changed += 1
    score = 100
    if not records:
        score -= 30
    if not enriched:
        score = 0
    return OrderedDict(
        [
            ("quality_score", max(score, 0)),
            ("status", "ok" if enriched else "empty"),
            ("items", len(enriched)),
            ("records", len(records)),
            ("changed_summaries", changed),
            ("success_records", status_counts.get("ok", 0)),
        ]
    )


def _evaluate_compress(outputs: dict[str, Any], context: dict[str, Any]) -> OrderedDict[str, Any]:
    transcripts = (outputs or {}).get("compressed_transcripts", []) or []
    raw = ((context.get("raw_sources") or {}).get("analysis_transcripts") or [])
    nonempty = 0
    ratios = []
    for source, compressed in zip(raw, transcripts, strict=False):
        out_text = str(compressed.get("compressed_transcript", "")).strip()
        if out_text:
            nonempty += 1
        in_words = max(1, len(str(source.get("transcript", "")).split()))
        out_words = len(out_text.split())
        ratios.append(out_words / in_words)
    avg_ratio = round(sum(ratios) / len(ratios), 3) if ratios else 0.0
    score = 100
    if raw and nonempty < len(raw):
        score -= 30
    if avg_ratio and (avg_ratio < 0.05 or avg_ratio > 0.65):
        score -= 15
    return OrderedDict(
        [
            ("quality_score", max(score, 0)),
            ("status", "ok" if transcripts else "empty"),
            ("transcripts", len(transcripts)),
            ("nonempty_outputs", nonempty),
            ("avg_compression_ratio", avg_ratio),
        ]
    )


def _evaluate_analyze_domain(outputs: dict[str, Any], context: dict[str, Any]) -> OrderedDict[str, Any]:
    domain_analysis = (outputs or {}).get("domain_analysis", {}) or {}
    failures = (outputs or {}).get("domain_analysis_failures", []) or []
    contract_issues = (outputs or {}).get("domain_analysis_contract_issues", []) or []
    total_items = 0
    populated_domains = 0
    my_read_ok = 0
    watch_for_hits = 0
    for result in domain_analysis.values():
        items = (result or {}).get("items", []) or []
        if items:
            populated_domains += 1
        total_items += len(items)
        for item in items:
            analysis = str(item.get("analysis", "")).strip()
            if analysis.startswith("My read:"):
                my_read_ok += 1
            if "watch for" in analysis.lower():
                watch_for_hits += 1
    my_read_pct = round(my_read_ok / total_items, 2) if total_items else 0.0
    watch_for_pct = round(watch_for_hits / total_items, 2) if total_items else 0.0
    source_count = len(((context.get("raw_sources") or {}).get("rss") or []))
    coverage_pct = round(total_items / source_count, 2) if source_count else 0.0
    score = 100
    if populated_domains < 4:
        score -= 20
    if my_read_pct < 1.0:
        score -= 20
    if watch_for_pct < 0.75:
        score -= 10
    if failures:
        score -= 20
    if contract_issues:
        score -= 15
    return OrderedDict(
        [
            ("quality_score", max(score, 0)),
            ("status", "ok" if total_items else "empty"),
            ("domains_with_items", populated_domains),
            ("total_items", total_items),
            ("my_read_pct", my_read_pct),
            ("watch_for_pct", watch_for_pct),
            ("coverage_vs_rss", coverage_pct),
            ("failures", len(failures)),
            ("contract_issues", len(contract_issues)),
        ]
    )


def _evaluate_spiritual_weekly(outputs: dict[str, Any], _context: dict[str, Any]) -> OrderedDict[str, Any]:
    weekly = (outputs or {}).get("spiritual_weekly", {}) or {}
    daily_foci = weekly.get("daily_foci", []) or []
    sequence = weekly.get("proposed_sequence", {}) or {}
    missing_guide = bool(weekly.get("missing_guide"))
    score = 100
    if missing_guide:
        score = 0
    elif not daily_foci:
        score -= 50
    elif len(sequence) < 5:
        score -= 15
    return OrderedDict(
        [
            ("quality_score", max(score, 0)),
            ("status", "fallback" if missing_guide else "ok"),
            ("daily_foci", len(daily_foci)),
            ("sequence_days", len(sequence)),
            ("missing_guide", missing_guide),
        ]
    )


def _evaluate_spiritual(outputs: dict[str, Any], _context: dict[str, Any]) -> OrderedDict[str, Any]:
    spiritual = (outputs or {}).get("spiritual", {}) or {}
    reflection = str(spiritual.get("reflection", "")).strip()
    words = len(reflection.split())
    fallback = reflection == str(spiritual.get("scripture_text", "")).strip()
    score = 100
    if not reflection:
        score = 0
    elif fallback:
        score -= 30
    if reflection and (words < 60 or words > 170):
        score -= 15
    return OrderedDict(
        [
            ("quality_score", max(score, 0)),
            ("status", "fallback" if fallback else "ok"),
            ("reflection_words", words),
            ("used_scripture_fallback", fallback),
        ]
    )


def _evaluate_seams(outputs: dict[str, Any], _context: dict[str, Any]) -> OrderedDict[str, Any]:
    candidates = ((outputs or {}).get("seam_candidates") or {}).get("candidates", []) or []
    per_item = ((outputs or {}).get("seam_annotations") or {}).get("per_item", []) or []
    cross_domain = ((outputs or {}).get("seam_annotations") or {}).get("cross_domain", []) or []
    seam_data = (outputs or {}).get("seam_data", {}) or {}
    quiet_day = bool(seam_data.get("quiet_day"))
    score = 100
    if not per_item and not cross_domain and not quiet_day:
        score -= 30
    return OrderedDict(
        [
            ("quality_score", max(score, 0)),
            ("status", "ok"),
            ("candidates", len(candidates)),
            ("per_item_annotations", len(per_item)),
            ("cross_domain_annotations", len(cross_domain)),
            ("quiet_day", quiet_day),
            ("seam_count", int(seam_data.get("seam_count", 0) or 0)),
        ]
    )


def _evaluate_cross_domain(outputs: dict[str, Any], _context: dict[str, Any]) -> OrderedDict[str, Any]:
    data = (outputs or {}).get("cross_domain_output", {}) or {}
    diagnostics = (outputs or {}).get("validation_diagnostics", {}) or {}
    contract_issues = (outputs or {}).get("cross_domain_contract_issues", []) or []
    glance = data.get("at_a_glance", []) or []
    dives = data.get("deep_dives", []) or []
    connections = data.get("cross_domain_connections", []) or []
    worth = data.get("worth_reading", []) or []
    valid_tags = {"war", "ai", "domestic", "defense", "space", "tech", "local", "science", "econ", "cyber", "energy", "biotech"}
    invalid_tags = sum(1 for item in glance if item.get("tag") not in valid_tags)
    score = 100
    if not glance:
        score = 0
    if invalid_tags:
        score -= 20
    if len(dives) > 3:
        score -= 10
    if diagnostics.get("issue_count"):
        score -= 20
    if contract_issues:
        score -= 15
    return OrderedDict(
        [
            ("quality_score", max(score, 0)),
            ("status", "ok" if glance else "empty"),
            ("at_a_glance", len(glance)),
            ("deep_dives", len(dives)),
            ("connections", len(connections)),
            ("worth_reading", len(worth)),
            ("invalid_tags", invalid_tags),
            ("validation_issues", int(diagnostics.get("issue_count", 0) or 0)),
            ("contract_issues", len(contract_issues)),
        ]
    )


def _evaluate_coverage_gaps(outputs: dict[str, Any], _context: dict[str, Any]) -> OrderedDict[str, Any]:
    data = (outputs or {}).get("coverage_gaps", {}) or {}
    gaps = data.get("gaps", []) or []
    recurring = data.get("recurring_patterns", []) or []
    high = sum(1 for gap in gaps if gap.get("significance") == "high")
    score = 100
    if not data:
        score = 0
    return OrderedDict(
        [
            ("quality_score", max(score, 0)),
            ("status", "ok" if data else "empty"),
            ("gaps", len(gaps)),
            ("high_significance", high),
            ("recurring_patterns", len(recurring)),
        ]
    )


_EVALUATORS: dict[str, Callable[[dict[str, Any], dict[str, Any]], OrderedDict[str, Any]]] = {
    "enrich_articles": _evaluate_enrich_articles,
    "compress": _evaluate_compress,
    "analyze_domain": _evaluate_analyze_domain,
    "prepare_spiritual_weekly": _evaluate_spiritual_weekly,
    "prepare_spiritual": _evaluate_spiritual,
    "seams": _evaluate_seams,
    "cross_domain": _evaluate_cross_domain,
    "coverage_gaps": _evaluate_coverage_gaps,
}


def summarize_reference(
    stage_name: str,
    reference_outputs: dict[str, Any],
    context: dict[str, Any],
) -> OrderedDict[str, Any]:
    evaluator = _EVALUATORS.get(stage_name, _evaluate_generic)
    metrics = evaluator(reference_outputs, context)
    metrics["status"] = "reference"
    return metrics


def build_stage_report_html(
    stage_name: str,
    run_date: str,
    results: list[dict[str, Any]],
    reference_summary: OrderedDict[str, Any],
) -> str:
    metric_names = list(reference_summary.keys())
    for result in results:
        for key in result.get("metrics", {}).keys():
            if key not in metric_names:
                metric_names.append(key)

    summary_rows = []
    for metric_name in metric_names:
        row = [f"<td>{html.escape(metric_name)}</td>"]
        row.append(f"<td>{html.escape(str(reference_summary.get(metric_name, '')))}</td>")
        for result in results:
            value = result.get("metrics", {}).get(metric_name, "")
            row.append(f"<td>{html.escape(str(value))}</td>")
        summary_rows.append("<tr>" + "".join(row) + "</tr>")

    header_cells = ["<th>Metric</th>", "<th>Reference</th>"]
    for result in results:
        label = result["label"]
        if "error" in result:
            label += " [error]"
        header_cells.append(f"<th>{html.escape(label)}</th>")

    raw_sections = []
    for result in results:
        body = json.dumps(result.get("outputs", {}), indent=2, ensure_ascii=False, default=str)
        raw_sections.append(
            f"""
            <div class="raw-section">
              <div class="raw-header" onclick="toggle('raw-{html.escape(result['model_key'])}')">
                {html.escape(result['label'])} raw output
              </div>
              <div class="raw-body" id="raw-{html.escape(result['model_key'])}">
                <pre>{html.escape(body)}</pre>
              </div>
            </div>
            """
        )

    notes = "".join(
        f"<li><strong>{html.escape(spec.label)}:</strong> {html.escape(spec.notes)}</li>"
        for spec in (MODEL_SPECS[result["model_key"]] for result in results)
        if spec.notes
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(stage_name)} stage comparison</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f6fa;
      color: #1f2933;
    }}
    .wrap {{ max-width: 1440px; margin: 0 auto; padding: 28px 24px 40px; }}
    h1 {{ margin: 0 0 6px; font-size: 1.7rem; }}
    .meta {{ color: #5f6c7b; font-size: 0.92rem; margin-bottom: 22px; }}
    .scorecard {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 10px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
      margin-bottom: 26px;
    }}
    .scorecard th {{
      text-align: left;
      background: #243b53;
      color: #fff;
      padding: 12px 14px;
      font-size: 0.9rem;
    }}
    .scorecard td {{
      padding: 10px 14px;
      border-bottom: 1px solid #e6edf3;
      vertical-align: top;
      font-size: 0.88rem;
    }}
    .scorecard tr:nth-child(even) td {{ background: #f8fafc; }}
    .notes {{
      background: #fff;
      border-radius: 10px;
      padding: 18px 20px;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
      margin-bottom: 22px;
    }}
    .notes ul {{ margin: 8px 0 0 18px; }}
    .raw-section {{
      background: #fff;
      border-radius: 10px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
      margin-bottom: 14px;
    }}
    .raw-header {{
      padding: 12px 14px;
      font-weight: 600;
      cursor: pointer;
      border-bottom: 1px solid #e6edf3;
      background: #f8fafc;
    }}
    .raw-body {{ display: none; }}
    .raw-body.open {{ display: block; }}
    pre {{
      margin: 0;
      padding: 16px;
      overflow-x: auto;
      background: #111827;
      color: #e5e7eb;
      font-size: 0.78rem;
      line-height: 1.45;
    }}
  </style>
  <script>
    function toggle(id) {{
      const el = document.getElementById(id);
      if (el) {{
        el.classList.toggle('open');
      }}
    }}
  </script>
</head>
<body>
  <div class="wrap">
    <h1>{html.escape(stage_name)} stage comparison</h1>
    <div class="meta">Fixture date: {html.escape(run_date)} · Models: {len(results)}</div>
    <table class="scorecard">
      <thead><tr>{''.join(header_cells)}</tr></thead>
      <tbody>{''.join(summary_rows)}</tbody>
    </table>
    <div class="notes">
      <strong>Model notes</strong>
      <ul>{notes}</ul>
    </div>
    {''.join(raw_sections)}
  </div>
</body>
</html>
"""


def build_index_html(run_date: str, stage_results: dict[str, list[dict[str, Any]]]) -> str:
    rows = []
    for stage_name, results in stage_results.items():
        ranked = sorted(
            results,
            key=lambda item: (
                int(item.get("metrics", {}).get("quality_score", 0)),
                -float(str(item.get("metrics", {}).get("est_cost_usd", "$0")).lstrip("$") or 0),
            ),
            reverse=True,
        )
        best = ranked[0] if ranked else {}
        report_path = best.get("report_html_path", "")
        link = html.escape(Path(report_path).name) if report_path else ""
        report_html = (
            f'<a href="{html.escape(Path(report_path).name)}">{link}</a>' if report_path else ""
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(stage_name)}</td>"
            f"<td>{html.escape(str(best.get('label', '')))}</td>"
            f"<td>{html.escape(str(best.get('metrics', {}).get('quality_score', '')))}</td>"
            f"<td>{html.escape(str(best.get('metrics', {}).get('est_cost_usd', '')))}</td>"
            f"<td>{report_html}</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Stage model comparison index</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f6fa;
      color: #1f2933;
    }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px 24px 40px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
      border-radius: 10px;
      overflow: hidden;
    }}
    th {{ text-align: left; background: #243b53; color: #fff; padding: 12px 14px; }}
    td {{ padding: 10px 14px; border-bottom: 1px solid #e6edf3; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Stage model comparison index</h1>
    <p>Fixture date: {html.escape(run_date)}</p>
    <table>
      <thead>
        <tr>
          <th>Stage</th>
          <th>Best quality score</th>
          <th>Score</th>
          <th>Estimated cost</th>
          <th>Report</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</body>
</html>
"""


def save_stage_outputs(
    output_dir: Path,
    stage_name: str,
    report_html: str,
    results: list[dict[str, Any]],
    reference_summary: OrderedDict[str, Any],
    timestamp: str,
) -> Path:
    stage_dir = output_dir / stage_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    report_path = stage_dir / f"comparison_{timestamp}.html"
    report_path.write_text(report_html, encoding="utf-8")

    summary_payload = {
        "stage": stage_name,
        "reference_summary": reference_summary,
        "results": [
            {
                "model_key": result["model_key"],
                "label": result["label"],
                "model_id": result["model_id"],
                "elapsed_s": result["elapsed_s"],
                "metrics": result["metrics"],
                "error": result.get("error"),
            }
            for result in results
        ],
    }
    (stage_dir / f"comparison_{timestamp}.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    for result in results:
        if "outputs" not in result:
            continue
        (stage_dir / f"{result['model_key']}_{timestamp}_output.json").write_text(
            json.dumps(result["outputs"], indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Per-stage Fireworks model comparison runner")
    parser.add_argument(
        "--stage",
        default="all",
        help="Stage name or 'all' (default: all)",
    )
    parser.add_argument(
        "--models",
        default="major",
        help="Model group ('major', 'new') or comma-separated model keys",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Artifact fixture date in YYYY-MM-DD format (default: most recent artifact date available in output/artifacts)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "output" / "stage_model_comparison"),
        help="Directory for HTML/JSON comparison artifacts",
    )
    return parser.parse_args()


def _default_run_date() -> str:
    artifacts_root = ROOT / "output" / "artifacts"
    dates = sorted(path.name for path in artifacts_root.iterdir() if path.is_dir())
    if not dates:
        raise FileNotFoundError(f"No artifact dirs found under {artifacts_root}")
    return dates[-1]


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    config = load_config(ROOT)
    stages = comparable_stage_names(config)
    if args.stage != "all":
        if args.stage not in stages:
            raise ValueError(f"Unknown comparable stage: {args.stage}")
        stages = [args.stage]

    model_keys = resolve_model_keys(args.models)
    models = [MODEL_SPECS[key] for key in model_keys]
    run_date = args.date or _default_run_date()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    all_results: dict[str, list[dict[str, Any]]] = {}
    for stage_name in stages:
        log.info("Comparing stage=%s against %d model(s)", stage_name, len(models))
        base_context, _stage_cfg, artifact_dir = load_stage_fixture(config, run_date, stage_name)
        reference_outputs = load_reference_outputs(stage_name, artifact_dir)
        reference_summary = summarize_reference(stage_name, reference_outputs, base_context)

        stage_results = [run_stage_once(config, run_date, stage_name, spec) for spec in models]
        report_html = build_stage_report_html(stage_name, run_date, stage_results, reference_summary)
        report_path = save_stage_outputs(
            output_dir,
            stage_name,
            report_html,
            stage_results,
            reference_summary,
            timestamp,
        )
        for result in stage_results:
            result["report_html_path"] = str(report_path)
        all_results[stage_name] = stage_results
        log.info("Wrote %s", report_path)

    index_html = build_index_html(run_date, all_results)
    index_path = output_dir / f"index_{timestamp}.html"
    index_path.write_text(index_html, encoding="utf-8")
    log.info("Wrote %s", index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
