"""Stage: seams — Produce per-item perspective annotations.

Seam detection operates on domain analysis artifacts and raw source data, then
first emits a broad diagnostic candidate scan. A second pass prunes those
candidate seams into item-level annotations keyed by stable domain-analysis item
IDs. A legacy `seam_data` projection is still returned so older downstream
consumers continue to receive a safe shape while rendering moves to inline
annotations.

Inputs:  domain_analysis (dict), raw_sources (dict), compressed_transcripts (list)
Outputs: seam_candidates (dict), seam_annotations (dict), seam_data (dict)

Non-critical: returns empty results on failure so the pipeline can continue.
"""

import logging
import json
from json import JSONDecodeError

from morning_digest.llm import call_llm
from utils.prompts import load_prompt

log = logging.getLogger(__name__)

_CANDIDATE_PROMPT = load_prompt("seam_candidates.md")
_ANNOTATION_PROMPT = load_prompt("seam_annotations.md")
_JSON_REPAIR_PROMPT = """You repair malformed JSON emitted by another model.

Return ONLY valid JSON.
Do not invent facts.
If a field is truncated or uncertain, drop the partial item or replace it with a safe empty default.
Preserve as much valid structure as possible.
"""
_VALID_SEAM_TYPES = {
    "framing_divergence",
    "selection_divergence",
    "causal_divergence",
    "magnitude_divergence",
    "credible_dissent",
}
_VALID_CONFIDENCE = {"high", "medium", "low"}


def _build_domain_summary(domain_analysis: dict) -> str:
    """Format domain analysis artifacts for the seam detection prompt."""
    parts = []
    for domain_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        items = domain_result.get("items", [])
        if not items:
            continue
        parts.append(f"\n--- {domain_key.upper()} ANALYSIS ({len(items)} items) ---")
        for item in items:
            dive_flag = (
                " [DEEP DIVE CANDIDATE]" if item.get("deep_dive_candidate") else ""
            )
            parts.append(
                f"\nItem ID: {item.get('item_id', '')}\n"
                f"Headline: {item.get('headline', '')}{dive_flag}\n"
                f"Tag: {item.get('tag', '')} | Depth: {item.get('source_depth', '')}\n"
                f"Facts: {item.get('facts', '')}\n"
                f"Analysis: {item.get('analysis', '')}"
            )
            if item.get("deep_dive_rationale"):
                parts.append(f"Dive rationale: {item['deep_dive_rationale']}")
            hooks = item.get("connection_hooks", [])
            if hooks:
                hook_strs = [
                    f"{h.get('entity', '?')}/{h.get('region', '?')}/{h.get('theme', '?')}"
                    for h in hooks[:3]
                ]
                parts.append(f"Connection hooks: {'; '.join(hook_strs)}")
            links = item.get("links", [])
            if links:
                link_strs = [
                    f"{l.get('label', '?')}: {l.get('url', '')}" for l in links[:3]
                ]
                parts.append(f"Links: {', '.join(link_strs)}")
        # Include market_context for econ
        if domain_key == "econ" and domain_result.get("market_context"):
            parts.append(f"\nMarket context: {domain_result['market_context']}")
    return "\n".join(parts) if parts else "(no domain analyses available)"


def _build_raw_source_summary(raw_sources: dict) -> str:
    """Format raw source data so seam detection can see what analysts had access to."""
    rss = raw_sources.get("rss", [])
    if not rss:
        return "(no raw source data)"

    # Group by category
    by_cat: dict[str, list[dict]] = {}
    for item in rss:
        cat = item.get("category", "uncategorized")
        by_cat.setdefault(cat, []).append(item)

    parts = []
    for cat, items in sorted(by_cat.items()):
        parts.append(f"\n--- {cat.upper()} ({len(items)} items) ---")
        for item in items[:12]:  # cap per category to manage prompt length
            reliability = item.get("reliability", "")
            rel_note = f" [{reliability}]" if reliability else ""
            parts.append(
                f"  {item.get('source', '?')}{rel_note}: "
                f"{item.get('title', '?')} — "
                f"{item.get('summary', '')[:500]}"
            )
            if item.get("url"):
                parts.append(f"    URL: {item['url']}")
    return "\n".join(parts)


def _build_transcript_summary(compressed_transcripts: list) -> str:
    """Format compressed transcripts for the seam detection prompt."""
    if not compressed_transcripts:
        return "(no transcripts)"
    parts = []
    for t in compressed_transcripts:
        text = t.get("compressed_transcript") or t.get("transcript", "")
        # Truncate for seam detection — it doesn't need the full transcript
        if len(text) > 500:
            text = text[:500] + "..."
        parts.append(f"{t.get('channel', '?')}: {t.get('title', '?')}\n  {text}")
    return "\n".join(parts)


def _annotation_user_content(
    domain_summary: str,
    raw_summary: str,
    transcript_summary: str,
    seam_candidates: dict,
) -> str:
    return f"""Use the broad candidate scan to produce the final per-item seam annotation artifact.

=== DOMAIN ANALYSES ===
{domain_summary}

=== RAW SOURCE DATA ===
{raw_summary}

=== COMPRESSED TRANSCRIPTS ===
{transcript_summary}

=== TURN 1 SEAM CANDIDATES ===
{json.dumps(seam_candidates, indent=2)}

Produce the final per-item seam annotation artifact. Output ONLY valid JSON."""


def _candidate_user_content(
    domain_summary: str, raw_summary: str, transcript_summary: str
) -> str:
    return f"""Review the following analytical products and source material.

=== DOMAIN ANALYSES ===
{domain_summary}

=== RAW SOURCE DATA ===
{raw_summary}

=== COMPRESSED TRANSCRIPTS ===
{transcript_summary}

Scan broadly for possible per-item and cross-domain seam candidates. Output ONLY valid JSON."""


def _empty_candidates() -> dict:
    return {"schema_version": 1, "candidates": [], "cross_domain_candidates": []}


def _resolve_turn_model_config(
    base_model_config: dict | None, stage_cfg: dict | None, turn_name: str
) -> dict | None:
    if not base_model_config:
        return None
    turn_overrides = (stage_cfg or {}).get("turns", {}).get(turn_name, {})
    return {**base_model_config, **turn_overrides}


def _empty_annotations() -> dict:
    return {"per_item": [], "cross_domain": []}


def _normalize_seam_candidates(result: dict | None, domain_analysis: dict) -> dict:
    if not isinstance(result, dict):
        return _empty_candidates()

    ids = _valid_item_ids(domain_analysis)
    candidates = []
    for raw_item in result.get("candidates", []) or []:
        if not isinstance(raw_item, dict):
            continue
        item_id = str(raw_item.get("item_id", "")).strip()
        if ids and item_id and item_id not in ids:
            log.warning(f"seams: dropping candidate for unknown item_id {item_id!r}")
            continue
        seam_type = str(raw_item.get("seam_type", "")).strip()
        if seam_type not in _VALID_SEAM_TYPES:
            continue
        candidates.append(
            {
                "item_id": item_id,
                "seam_type": seam_type,
                "candidate_one_line": str(
                    raw_item.get("candidate_one_line", "")
                ).strip(),
                "why_it_might_matter": str(
                    raw_item.get("why_it_might_matter", "")
                ).strip(),
                "possible_evidence": [
                    {
                        "source": str(entry.get("source", "")).strip(),
                        "excerpt": str(entry.get("excerpt", "")).strip(),
                        "framing": str(entry.get("framing", "")).strip(),
                    }
                    for entry in (raw_item.get("possible_evidence", []) or [])
                    if isinstance(entry, dict)
                ],
                "drop_if_weak_reason": str(
                    raw_item.get("drop_if_weak_reason", "")
                ).strip(),
            }
        )

    cross_domain_candidates = []
    for raw_item in result.get("cross_domain_candidates", []) or []:
        if not isinstance(raw_item, dict):
            continue
        linked_ids = [
            str(item_id).strip()
            for item_id in raw_item.get("linked_item_ids", []) or []
            if str(item_id).strip()
        ]
        if ids:
            linked_ids = [item_id for item_id in linked_ids if item_id in ids]
        if len(linked_ids) < 2:
            continue
        cross_domain_candidates.append(
            {
                "candidate_one_line": str(
                    raw_item.get("candidate_one_line", "")
                ).strip(),
                "linked_item_ids": linked_ids,
                "why_it_might_matter": str(
                    raw_item.get("why_it_might_matter", "")
                ).strip(),
            }
        )

    return {
        "schema_version": 1,
        "candidates": candidates,
        "cross_domain_candidates": cross_domain_candidates,
    }


def _valid_item_ids(domain_analysis: dict) -> set[str]:
    ids: set[str] = set()
    for domain_result in domain_analysis.values():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []):
            item_id = str(item.get("item_id", "")).strip()
            if item_id:
                ids.add(item_id)
    return ids


def _normalize_confidence(value: str) -> str:
    confidence = str(value or "medium").strip().lower()
    return confidence if confidence in _VALID_CONFIDENCE else "medium"


def _evidence_passes_gate(evidence: object) -> bool:
    if not isinstance(evidence, list) or len(evidence) < 2:
        return False
    distinct_sources: set[str] = set()
    useful_excerpts = 0
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("source", "")).strip()
        excerpt = str(entry.get("excerpt", "")).strip()
        if source:
            distinct_sources.add(source.lower())
        if excerpt:
            useful_excerpts += 1
    return len(distinct_sources) >= 2 and useful_excerpts >= 2


def _validate_seam_annotations(result: dict | None, domain_analysis: dict) -> dict:
    """Validate the load-bearing seam annotation schema.

    The evidence gate is intentionally structural: if two distinct sourced
    excerpts are not present, the item annotation is dropped.
    """
    if not isinstance(result, dict):
        return _empty_annotations()

    ids = _valid_item_ids(domain_analysis)
    cleaned_per_item: list[dict] = []
    for raw_item in result.get("per_item", []) or []:
        if not isinstance(raw_item, dict):
            continue
        item_id = str(raw_item.get("item_id", "")).strip()
        if ids and item_id not in ids:
            log.warning(f"seams: dropping annotation for unknown item_id {item_id!r}")
            continue
        seam_type = str(raw_item.get("seam_type", "")).strip()
        if seam_type not in _VALID_SEAM_TYPES:
            log.warning(f"seams: dropping annotation with invalid type {seam_type!r}")
            continue
        evidence = raw_item.get("evidence", [])
        if not _evidence_passes_gate(evidence):
            log.warning(
                f"seams: dropping annotation for {item_id!r}; evidence gate failed"
            )
            continue

        cleaned_evidence = []
        for entry in evidence:
            if not isinstance(entry, dict):
                continue
            cleaned_evidence.append(
                {
                    "source": str(entry.get("source", "")).strip(),
                    "excerpt": str(entry.get("excerpt", "")).strip(),
                    "framing": str(entry.get("framing", "")).strip(),
                }
            )

        cleaned_per_item.append(
            {
                "item_id": item_id,
                "seam_type": seam_type,
                "one_line": str(raw_item.get("one_line", "")).strip(),
                "evidence": cleaned_evidence,
                "confidence": _normalize_confidence(raw_item.get("confidence", "")),
            }
        )

    cleaned_cross_domain: list[dict] = []
    for raw_item in result.get("cross_domain", []) or []:
        if not isinstance(raw_item, dict):
            continue
        linked_ids = [
            str(item_id).strip()
            for item_id in raw_item.get("linked_item_ids", []) or []
            if str(item_id).strip()
        ]
        if ids:
            linked_ids = [item_id for item_id in linked_ids if item_id in ids]
        if len(linked_ids) < 2:
            continue
        cleaned_cross_domain.append(
            {
                "seam_type": "cross_desk",
                "one_line": str(raw_item.get("one_line", "")).strip(),
                "linked_item_ids": linked_ids,
            }
        )

    return {"per_item": cleaned_per_item, "cross_domain": cleaned_cross_domain}


def _legacy_seam_data(seam_annotations: dict) -> dict:
    """Project annotations into the old seam_data shape for compatibility."""
    contested = []
    coverage_gaps = []
    for annotation in seam_annotations.get("per_item", []):
        entry = {
            "topic": annotation.get("item_id", ""),
            "description": annotation.get("one_line", ""),
            "links": [],
            "sources_a": "",
            "sources_b": "",
            "analytical_significance": annotation.get("seam_type", ""),
        }
        if annotation.get("seam_type") == "selection_divergence":
            coverage_gaps.append(
                {
                    "topic": annotation.get("item_id", ""),
                    "description": annotation.get("one_line", ""),
                    "present_in": "",
                    "absent_from": "",
                    "links": [],
                }
            )
        else:
            contested.append(entry)

    total = len(contested) + len(coverage_gaps)
    return {
        "contested_narratives": contested,
        "coverage_gaps": coverage_gaps,
        "key_assumptions": [],
        "seam_count": total,
        "quiet_day": total <= 1,
    }


def _call_turn_json(
    prompt: str,
    user_content: str,
    model_config: dict | None,
    turn_name: str,
    fallback_shape: dict,
) -> dict:
    """Call a seams turn, retrying once without streaming and then repairing JSON."""
    raw_attempts: list[str] = []
    for stream in (True, False):
        try:
            raw = call_llm(
                prompt,
                user_content,
                model_config,
                max_retries=1,
                json_mode=False,
                stream=stream,
            )
            raw_attempts.append(raw)
            if isinstance(raw, dict):
                return raw
            return _parse_turn_json(raw)
        except Exception as exc:
            if stream:
                log.warning(
                    f"seams: {turn_name} turn failed with streaming, retrying once: {exc}"
                )
            else:
                log.warning(
                    f"seams: {turn_name} turn still failed without streaming: {exc}"
                )

    if raw_attempts:
        try:
            return _repair_turn_json(
                raw_attempts[-1], model_config, turn_name, fallback_shape
            )
        except Exception as exc:
            log.warning(f"seams: {turn_name} JSON repair failed: {exc}")

    return dict(fallback_shape)


def _parse_turn_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except JSONDecodeError:
        decoder = json.JSONDecoder()
        parsed, _end = decoder.raw_decode(text)
        return parsed


def _repair_turn_json(
    raw: str,
    model_config: dict | None,
    turn_name: str,
    fallback_shape: dict,
) -> dict:
    repair_config = dict(model_config or {})
    repair_config["max_tokens"] = min(repair_config.get("max_tokens", 4000), 4000)
    repair_request = f"""Repair this malformed {turn_name} JSON into valid JSON.

Target shape:
{json.dumps(fallback_shape, indent=2)}

Malformed JSON:
{raw}
"""
    return call_llm(
        _JSON_REPAIR_PROMPT,
        repair_request,
        repair_config,
        max_retries=1,
        json_mode=True,
        stream=False,
    )


def _empty_seam_result() -> dict:
    empty_annotations = _empty_annotations()
    empty_candidates = _empty_candidates()
    return {
        "seam_candidates": empty_candidates,
        "seam_scan": empty_candidates,
        "seam_annotations": empty_annotations,
        "seam_data": _legacy_seam_data(empty_annotations),
    }


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Detect per-item seam annotations."""
    domain_analysis = context.get("domain_analysis", {})
    raw_sources = context.get("raw_sources", {})
    compressed_transcripts = context.get("compressed_transcripts", [])

    effective_config = model_config or config.get("llm", {}).get(
        "seam_detection",
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "max_tokens": 8192,
            "temperature": 0.3,
        },
    )
    stage_cfg = kwargs.get("stage_cfg") or {}
    candidate_config = _resolve_turn_model_config(
        effective_config, stage_cfg, "candidates"
    )
    annotation_config = _resolve_turn_model_config(
        effective_config, stage_cfg, "annotations"
    )

    domain_summary = _build_domain_summary(domain_analysis)
    raw_summary = _build_raw_source_summary(raw_sources)
    transcript_summary = _build_transcript_summary(compressed_transcripts)

    try:
        log.info("Stage: seams — scanning broad seam candidates...")
        seam_candidates_raw = _call_turn_json(
            _CANDIDATE_PROMPT,
            _candidate_user_content(domain_summary, raw_summary, transcript_summary),
            candidate_config,
            "candidates",
            _empty_candidates(),
        )
        seam_candidates = _normalize_seam_candidates(
            seam_candidates_raw, domain_analysis
        )

        log.info("Stage: seams — pruning candidates into per-item annotations...")
        result = _call_turn_json(
            _ANNOTATION_PROMPT,
            _annotation_user_content(
                domain_summary,
                raw_summary,
                transcript_summary,
                seam_candidates,
            ),
            annotation_config,
            "annotations",
            _empty_annotations(),
        )
        seam_annotations = _validate_seam_annotations(result, domain_analysis)
        seam_data = _legacy_seam_data(seam_annotations)

        log.info(
            f"  Seam annotations: {len(seam_annotations['per_item'])} per-item, "
            f"{len(seam_annotations['cross_domain'])} cross-domain"
        )
        return {
            "seam_candidates": seam_candidates,
            "seam_scan": seam_candidates,
            "seam_annotations": seam_annotations,
            "seam_data": seam_data,
        }

    except Exception as e:
        log.warning(f"Seam detection failed (non-fatal): {e}")
        return _empty_seam_result()
