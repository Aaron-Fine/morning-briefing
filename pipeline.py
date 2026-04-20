#!/usr/bin/env python3
"""Morning Digest v2 — Staged Pipeline Orchestrator.

Replaces the monolithic digest.py with a stage-based pipeline that:
  - Executes stages in dependency order defined in config.yaml
  - Persists each stage's output as JSON artifacts in output/artifacts/{YYYY-MM-DD}/
  - Supports re-running any single stage from the command line (--stage NAME)
  - Logs timing per stage
  - Retries failed stages with exponential backoff
  - Gracefully degrades when non-critical stages fail
  - Retains artifacts for 30 days

Usage:
  python pipeline.py                         # full run (schedule mode via entrypoint)
  python pipeline.py --dry-run               # full run, skip email send
   python pipeline.py --stage cross_domain    # re-run from cross_domain onwards
  python pipeline.py --sources-only          # collect sources and dump, skip LLM
  python pipeline.py --lookback-hours 72    # override YouTube lookback window
"""

import argparse
from copy import deepcopy
import json
import logging
import logging.handlers
import sys
import time
from datetime import timedelta
from pathlib import Path

import yaml
from utils.time import artifact_date, iso_now_local, now_local

log = logging.getLogger("pipeline")

_ROOT = Path(__file__).parent
_OUTPUT_DIR = _ROOT / "output"
_ARTIFACTS_BASE = _OUTPUT_DIR / "artifacts"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config() -> dict:
    with open(_ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_log_file() -> None:
    _OUTPUT_DIR.mkdir(exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(
        _OUTPUT_DIR / "digest.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(handler)


# ---------------------------------------------------------------------------
# Artifact persistence
# ---------------------------------------------------------------------------


def _artifact_dir(run_date: str) -> Path:
    d = _ARTIFACTS_BASE / run_date
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_artifact(artifact_dir: Path, name: str, data) -> None:
    """Save a stage output value as a JSON file."""
    path = artifact_dir / f"{name}.json"
    try:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        log.warning(f"Failed to save artifact {name}.json: {e}")


def _load_artifact(artifact_dir: Path, name: str):
    """Load a previously saved artifact. Returns None if not found."""
    path = artifact_dir / f"{name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"Failed to load artifact {name}.json: {e}")
    return None


def _find_most_recent_artifact_dir(before_date: str | None = None) -> Path | None:
    """Find the most recent artifact directory (optionally before a given date)."""
    if not _ARTIFACTS_BASE.exists():
        return None
    dirs = sorted(
        [d for d in _ARTIFACTS_BASE.iterdir() if d.is_dir() and len(d.name) == 10],
        reverse=True,
    )
    for d in dirs:
        if before_date and d.name >= before_date:
            continue
        return d
    return None


def _prune_artifacts(keep_days: int = 30) -> None:
    """Delete artifact directories older than keep_days."""
    if not _ARTIFACTS_BASE.exists():
        return
    cutoff = now_local() - timedelta(days=keep_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    for d in _ARTIFACTS_BASE.iterdir():
        if d.is_dir() and len(d.name) == 10 and d.name < cutoff_str:
            import shutil

            shutil.rmtree(d, ignore_errors=True)
            log.debug(f"Pruned artifact dir: {d.name}")

    # Also prune old dated HTML files in output/
    cutoff_ts = cutoff.timestamp()
    for f in _OUTPUT_DIR.glob("????-??-??.html"):
        if f.stat().st_mtime < cutoff_ts:
            f.unlink(missing_ok=True)
            log.debug(f"Pruned old digest HTML: {f.name}")


# ---------------------------------------------------------------------------
# Stage registry — maps stage name → module
# ---------------------------------------------------------------------------


def _load_stage_module(name: str):
    """Dynamically import a stage module by name."""
    import importlib

    return importlib.import_module(f"stages.{name}")


def _load_previous_cross_domain(context: dict, *, run_date: str, **_kwargs) -> None:
    """Inject the previous day's cross-domain output when available."""
    prev_dir = _find_most_recent_artifact_dir(before_date=run_date)
    if not prev_dir:
        return

    prev_xd = _load_artifact(prev_dir, "cross_domain_output")
    if prev_xd:
        context["previous_cross_domain"] = prev_xd
        log.info(f"  Loaded previous cross_domain from {prev_dir.name}")


def _load_same_day_cross_domain_plan(
    context: dict,
    *,
    artifact_dir: Path,
    stage_from: str | None = None,
    from_plan: bool = False,
    **_kwargs,
) -> None:
    """Optionally preload the same-day cross-domain plan for execution-only reruns."""
    if not from_plan or stage_from != "cross_domain":
        return

    plan = _load_artifact(artifact_dir, "cross_domain_plan")
    if isinstance(plan, dict):
        context["cross_domain_plan"] = plan
        context["cross_domain_from_plan"] = True
        log.info("  Loaded same-day cross_domain_plan for --from-plan reuse")
    else:
        log.info("  No readable same-day cross_domain_plan found; recomputing Turn 1")


def _prepare_cross_domain_context(context: dict, **kwargs) -> None:
    """Load continuity context and optional same-day plan reuse inputs."""
    _load_previous_cross_domain(context, **kwargs)
    # Validity rules for reusing a saved plan may tighten over time if needed.
    _load_same_day_cross_domain_plan(context, **kwargs)


def _write_assemble_outputs(
    context: dict,
    outputs: dict,
    *,
    artifact_dir: Path,
    run_date: str,
    dry_run: bool,
    **_kwargs,
) -> None:
    """Persist the rendered digest HTML for the assemble stage."""
    html = outputs.get("html") or context.get("html", "")
    if not html:
        return

    (artifact_dir / "digest.html").write_text(html, encoding="utf-8")
    (_OUTPUT_DIR / "last_digest.html").write_text(html, encoding="utf-8")
    if not dry_run:
        (_OUTPUT_DIR / f"{run_date}.html").write_text(html, encoding="utf-8")


def _load_cached_assemble_outputs(context: dict, *, artifact_dir: Path, **_kwargs) -> None:
    """Reload assemble outputs, including the rendered HTML sidecar file."""
    for key in ("template_data", "digest_json"):
        artifact_data = _load_artifact(artifact_dir, key)
        if artifact_data is not None:
            context[key] = artifact_data

    html_path = artifact_dir / "digest.html"
    if html_path.exists():
        context["html"] = html_path.read_text(encoding="utf-8")


_STAGE_METADATA = {
    "collect": {
        "artifact_key": "raw_sources",
        "context_keys": ["raw_sources"],
        "non_critical": False,
        "empty_output": None,
        "model_defaults": None,
        "turn_model_overrides": None,
    },
    "enrich_articles": {
        "artifact_key": "enrich_articles",
        "context_keys": ["raw_sources", "enrich_articles"],
        "non_critical": True,
        "empty_output": {"enrich_articles": {"records": []}},
        "model_defaults": {},
        "turn_model_overrides": None,
    },
    "compress": {
        "artifact_key": "compressed_transcripts",
        "context_keys": ["compressed_transcripts"],
        "non_critical": True,
        "empty_output": {"compressed_transcripts": []},
        "model_defaults": {},
        "turn_model_overrides": None,
    },
    "analyze_domain": {
        "artifact_key": "domain_analysis",
        "context_keys": ["domain_analysis"],
        "non_critical": False,
        "empty_output": None,
        "model_defaults": {},
        "turn_model_overrides": None,
    },
    "prepare_calendar": {
        "artifact_key": "calendar",
        "context_keys": ["calendar"],
        "non_critical": False,
        "empty_output": None,
        "model_defaults": None,
        "turn_model_overrides": None,
    },
    "prepare_weather": {
        "artifact_key": "weather",
        "context_keys": ["weather", "weather_html"],
        "non_critical": True,
        "empty_output": {"weather": {}, "weather_html": ""},
        "model_defaults": None,
        "turn_model_overrides": None,
    },
    "prepare_spiritual_weekly": {
        "artifact_key": "spiritual_weekly",
        "context_keys": ["spiritual_weekly"],
        "non_critical": True,
        "empty_output": {"spiritual_weekly": {}},
        "model_defaults": {},
        "turn_model_overrides": None,
    },
    "prepare_spiritual": {
        "artifact_key": "spiritual",
        "context_keys": ["spiritual"],
        "non_critical": True,
        "empty_output": {"spiritual": {}},
        "model_defaults": {},
        "turn_model_overrides": None,
    },
    "prepare_local": {
        "artifact_key": "local_items",
        "context_keys": ["local_items"],
        "non_critical": True,
        "empty_output": {"local_items": []},
        "model_defaults": None,
        "turn_model_overrides": None,
    },
    "seams": {
        "artifact_key": "seam_data",
        "context_keys": ["seam_candidates", "seam_scan", "seam_annotations", "seam_data"],
        "non_critical": True,
        "empty_output": {
            "seam_candidates": {
                "schema_version": 1,
                "candidates": [],
                "cross_domain_candidates": [],
            },
            "seam_scan": {
                "schema_version": 1,
                "candidates": [],
                "cross_domain_candidates": [],
            },
            "seam_annotations": {"per_item": [], "cross_domain": []},
            "seam_data": {
                "contested_narratives": [],
                "coverage_gaps": [],
                "key_assumptions": [],
                "seam_count": 0,
                "quiet_day": True,
            }
        },
        "model_defaults": {},
        "turn_model_overrides": None,
    },
    "cross_domain": {
        "artifact_key": "cross_domain_output",
        "context_keys": ["cross_domain_plan", "cross_domain_output"],
        "non_critical": False,
        "empty_output": None,
        "model_defaults": {},
        "turn_model_overrides": None,
        "before_run": _prepare_cross_domain_context,
    },
    "coverage_gaps": {
        "artifact_key": "coverage_gaps",
        "context_keys": ["coverage_gaps"],
        "non_critical": True,
        "empty_output": {
            "coverage_gaps": {
                "schema_version": 1,
                "date": "",
                "gaps": [],
                "recurring_patterns": [],
            }
        },
        "model_defaults": {},
        "turn_model_overrides": None,
    },
    "assemble": {
        "artifact_key": "digest_json",
        "context_keys": ["template_data", "digest_json"],
        "non_critical": False,
        "empty_output": None,
        "model_defaults": None,
        "turn_model_overrides": None,
        "after_run": _write_assemble_outputs,
        "load_cached": _load_cached_assemble_outputs,
    },
    "anomaly": {
        "artifact_key": "anomaly_report",
        "context_keys": ["anomaly_report"],
        "non_critical": True,
        "empty_output": {
            "anomaly_report": {"anomalies": [], "checks_run": 0, "anomaly_count": 0}
        },
        "model_defaults": None,
        "turn_model_overrides": None,
    },
    "briefing_packet": {
        "artifact_key": "briefing_packet",
        "context_keys": ["briefing_packet"],
        "non_critical": True,
        "empty_output": {"briefing_packet": {}},
        "model_defaults": None,
        "turn_model_overrides": None,
    },
    "send": {
        "artifact_key": "send_result",
        "context_keys": ["send_result"],
        "non_critical": False,
        "empty_output": None,
        "model_defaults": None,
        "turn_model_overrides": None,
    },
}

# Stages that are allowed to fail without aborting the pipeline.
# A failed non-critical stage produces an empty output and logs a warning.
_NON_CRITICAL_STAGES = {
    stage_name
    for stage_name, meta in _STAGE_METADATA.items()
    if meta.get("non_critical")
}


def _get_stage_meta(stage_name: str) -> dict:
    """Return canonical stage metadata with safe defaults for unknown stages."""
    meta = _STAGE_METADATA.get(stage_name, {})
    artifact_key = meta.get("artifact_key", stage_name)
    context_keys = meta.get("context_keys", [artifact_key])
    return {
        "artifact_key": artifact_key,
        "context_keys": context_keys,
        "non_critical": meta.get("non_critical", False),
        "empty_output": deepcopy(meta.get("empty_output")),
        "model_defaults": deepcopy(meta.get("model_defaults")),
        "turn_model_overrides": deepcopy(meta.get("turn_model_overrides")),
        "before_run": meta.get("before_run"),
        "after_run": meta.get("after_run"),
        "load_cached": meta.get("load_cached"),
    }


def _load_cached_stage_outputs(stage_name: str, context: dict, artifact_dir: Path) -> None:
    """Reload all cached outputs for a skipped stage."""
    meta = _get_stage_meta(stage_name)
    custom_loader = meta.get("load_cached")
    if custom_loader:
        custom_loader(context, artifact_dir=artifact_dir)
        return

    for key in meta["context_keys"]:
        artifact_data = _load_artifact(artifact_dir, key)
        if artifact_data is not None:
            context[key] = artifact_data


def _run_stage_before_hook(stage_name: str, context: dict, **kwargs) -> None:
    """Run any stage-specific pre-execution lifecycle hook."""
    hook = _get_stage_meta(stage_name).get("before_run")
    if hook:
        hook(context, **kwargs)


def _run_stage_after_hook(stage_name: str, context: dict, outputs: dict, **kwargs) -> None:
    """Run any stage-specific post-execution lifecycle hook."""
    hook = _get_stage_meta(stage_name).get("after_run")
    if hook:
        hook(context, outputs, **kwargs)


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def _run_with_retry(fn, stage_name: str, max_retries: int = 2):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt < max_retries:
                wait = 2 ** (attempt + 1) * 5  # 10s, 20s
                log.warning(
                    f"Stage '{stage_name}' failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


def _get_stage_model_config(
    stage_cfg: dict,
    stage_name: str | None = None,
    config: dict | None = None,
) -> dict | None:
    """Resolve stage model config from global defaults, metadata, and manifest overrides."""
    stage_meta = _get_stage_meta(stage_name or stage_cfg.get("name", ""))
    manifest_model = stage_cfg.get("model")
    if manifest_model is None and stage_meta["model_defaults"] is None:
        return None

    resolved = {}
    if config:
        resolved.update(config.get("llm", {}))
    if stage_meta["model_defaults"]:
        resolved.update(stage_meta["model_defaults"])
    if manifest_model:
        resolved.update(manifest_model)
    return resolved or None


def run_pipeline(
    dry_run: bool = False,
    sources_only: bool = False,
    lookback_hours: int | None = None,
    stage_from: str | None = None,
    from_plan: bool = False,
) -> None:
    """Execute the full pipeline.

    Args:
        dry_run:       Skip the send stage; save HTML to output/ only.
        sources_only:  Run only the collect stage and dump sources.json.
        lookback_hours: Override YouTube lookback window.
        stage_from:    If set, load prior artifacts and re-run from this stage onwards.
    """
    _setup_log_file()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log.info("=== Morning Digest pipeline starting ===")

    config = load_config()

    # Apply CLI overrides
    if lookback_hours is not None:
        config.setdefault("youtube", {})["lookback_hours"] = lookback_hours
        log.info(f"  Override: lookback_hours={lookback_hours}")
    run_date = artifact_date()
    artifact_dir = _artifact_dir(run_date)
    log.info(f"  Artifact dir: {artifact_dir}")

    # Load pipeline stage manifest from config
    stage_manifest = config.get("pipeline", {}).get("stages", [])
    if not stage_manifest:
        log.error("No pipeline.stages defined in config.yaml")
        sys.exit(1)

    # Determine which stages to skip (loading from artifacts) vs. run
    stage_names = [s["name"] for s in stage_manifest]
    if stage_from and stage_from not in stage_names:
        log.error(f"Unknown stage: '{stage_from}'. Valid stages: {stage_names}")
        sys.exit(1)
    if from_plan and stage_from != "cross_domain":
        log.error("--from-plan is only supported with --stage cross_domain")
        sys.exit(1)

    skip_before = stage_from  # stages before this are loaded from artifacts

    # Determine artifact source directory for loading prior stage outputs
    # Try today's dir first, then most recent prior run
    def _find_load_dir() -> Path | None:
        if any(
            (_artifact_dir(run_date) / f"{s}.json").exists()
            for s in ["raw_sources", "synthesis_output"]
        ):
            return artifact_dir
        return _find_most_recent_artifact_dir(before_date=run_date)

    load_dir = _find_load_dir() if stage_from else artifact_dir

    # Accumulated context: union of all stage outputs
    context: dict = {}

    # Pipeline run metadata
    run_meta = {
        "run_date": run_date,
        "started_at": iso_now_local(),
        "stage_timings": {},
        "stage_failures": [],
        "options": {
            "dry_run": dry_run,
            "sources_only": sources_only,
            "lookback_hours": lookback_hours,
            "stage_from": stage_from,
            "from_plan": from_plan,
        },
    }

    _OUTPUT_DIR.mkdir(exist_ok=True)

    for stage_cfg in stage_manifest:
        stage_name = stage_cfg["name"]
        stage_meta = _get_stage_meta(stage_name)
        model_config = _get_stage_model_config(stage_cfg, stage_name=stage_name, config=config)

        # --sources-only: stop after collect
        if sources_only and stage_name != "collect":
            break

        # --dry-run: skip send
        if dry_run and stage_name == "send":
            log.info(f"  [dry-run] Skipping stage: {stage_name}")
            continue

        # If running from a specific stage, load prior outputs from artifacts
        if skip_before and stage_name != skip_before and stage_name in stage_names:
            idx_current = stage_names.index(stage_name)
            idx_from = stage_names.index(skip_before)
            if idx_current < idx_from:
                log.info(f"  Loading cached artifact for skipped stage: {stage_name}")
                if load_dir:
                    _load_cached_stage_outputs(stage_name, context, load_dir)
                continue  # don't execute this stage

        _run_stage_before_hook(
            stage_name,
            context,
            run_date=run_date,
            artifact_dir=artifact_dir,
            dry_run=dry_run,
            load_dir=load_dir,
            config=config,
            stage_from=stage_from,
            from_plan=from_plan,
        )

        # Execute the stage
        log.info(f"--- Stage: {stage_name} ---")
        t_start = time.monotonic()

        try:
            module = _load_stage_module(stage_name)

            outputs = _run_with_retry(
                lambda m=module: m.run(
                    context, config, model_config, stage_cfg=stage_cfg, dry_run=dry_run
                ),
                stage_name,
                max_retries=2,
            )

        except Exception as e:
            elapsed = time.monotonic() - t_start
            run_meta["stage_timings"][stage_name] = round(elapsed, 2)

            if stage_meta["non_critical"]:
                log.warning(
                    f"Stage '{stage_name}' failed after retries (non-critical, continuing): {e}"
                )
                run_meta["stage_failures"].append(
                    {"stage": stage_name, "error": str(e)}
                )
                # Provide safe empty outputs so downstream stages don't crash
                outputs = _empty_stage_output(stage_name)
            else:
                log.error(f"Stage '{stage_name}' failed (critical): {e}")
                run_meta["stage_failures"].append(
                    {"stage": stage_name, "error": str(e), "fatal": True}
                )
                _save_artifact(artifact_dir, "run_meta", run_meta)
                sys.exit(1)

        elapsed = time.monotonic() - t_start
        run_meta["stage_timings"][stage_name] = round(elapsed, 2)
        log.info(f"  Stage '{stage_name}' completed in {elapsed:.1f}s")

        # Merge outputs into context
        context.update(outputs)

        # Persist each output artifact
        for key, value in outputs.items():
            if key not in ("html",):  # don't double-write html; handled below
                _save_artifact(artifact_dir, key, value)

        _run_stage_after_hook(
            stage_name,
            context,
            outputs,
            artifact_dir=artifact_dir,
            run_date=run_date,
            dry_run=dry_run,
            load_dir=load_dir,
            config=config,
        )

        # --sources-only: dump sources.json after collect and exit
        if sources_only and stage_name == "collect":
            out = _OUTPUT_DIR / "sources.json"
            out.write_text(
                json.dumps(context.get("raw_sources", {}), indent=2, default=str),
                encoding="utf-8",
            )
            log.info(f"=== Sources written to {out} ===")
            return

    # Finalize run metadata
    run_meta["finished_at"] = iso_now_local()
    _save_artifact(artifact_dir, "run_meta", run_meta)

    # Prune old artifacts
    _prune_artifacts(keep_days=30)

    if dry_run:
        log.info(
            f"=== Dry run complete — digest saved to {_OUTPUT_DIR / 'last_digest.html'} ==="
        )
    else:
        send_result = context.get("send_result", {})
        if send_result.get("success"):
            log.info("=== Digest sent successfully ===")
        else:
            log.error("=== Pipeline completed but digest send failed ===")
            sys.exit(1)


def _stage_artifact_key(stage_name: str) -> str:
    """Map stage name to its primary output artifact key."""
    return _get_stage_meta(stage_name)["artifact_key"]


def _empty_stage_output(stage_name: str) -> dict:
    """Return safe empty outputs for a failed non-critical stage."""
    return _get_stage_meta(stage_name)["empty_output"] or {}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Morning Digest v2 pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run full pipeline but save HTML to output/ instead of sending email",
    )
    parser.add_argument(
        "--sources-only",
        action="store_true",
        help="Collect sources and dump to output/sources.json; skip LLM and email",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=None,
        help="Override YouTube lookback_hours (e.g. 120 to catch older videos)",
    )
    parser.add_argument(
        "--stage",
        metavar="NAME",
        default=None,
        help="Re-run from this stage onwards, loading prior stage artifacts from disk",
    )
    parser.add_argument(
        "--from-plan",
        action="store_true",
        help="With --stage cross_domain, reuse same-day cross_domain_plan.json when readable",
    )
    args = parser.parse_args()

    run_pipeline(
        dry_run=args.dry_run,
        sources_only=args.sources_only,
        lookback_hours=args.lookback_hours,
        stage_from=args.stage,
        from_plan=args.from_plan,
    )


if __name__ == "__main__":
    main()
