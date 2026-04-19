"""Stage: seams — Detect narrative disagreements, coverage gaps, and key assumptions.

Phase 2 seam detection operates on domain analysis artifacts AND raw source data,
not just synthesized output. This gives it access to source-level framing that the
domain analysis passes may have smoothed over.

Three detection modes (all in one LLM call):
  1. Contested Narratives — where source categories frame the same event differently
  2. Coverage Gaps — stories present in some categories but absent from analyses
  3. Key Assumptions Check — IC-style identification of unstated analytical assumptions

The seam detection model should have DIFFERENT training biases than the domain
analysis model (Kimi K2.5) to provide bias diversity. Default: Claude Sonnet.

Inputs:  domain_analysis (dict), raw_sources (dict), compressed_transcripts (list)
Outputs: seam_data (dict)

Non-critical: returns empty results on failure so the pipeline can continue.
"""

import logging
import json

from morning_digest.llm import call_llm
from utils.prompts import load_prompt
from morning_digest.validate import validate_stage_output

log = logging.getLogger(__name__)

_SCAN_PROMPT = load_prompt("seams_scan.md")
_SYNTHESIS_PROMPT = load_prompt("seams_synthesis.md")


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
                f"\nHeadline: {item.get('headline', '')}{dive_flag}\n"
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
                f"{item.get('summary', '')[:200]}"
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


def _scan_user_content(
    domain_summary: str, raw_summary: str, transcript_summary: str
) -> str:
    return f"""Review the following analytical products and source material.

=== DOMAIN ANALYSES ===
{domain_summary}

=== RAW SOURCE DATA ===
{raw_summary}

=== COMPRESSED TRANSCRIPTS ===
{transcript_summary}

Scan broadly for tensions, absences, and assumptions. Output ONLY valid JSON."""


def _synthesis_user_content(
    domain_summary: str,
    raw_summary: str,
    transcript_summary: str,
    seam_scan: dict,
) -> str:
    return f"""Use the scan findings to produce the final seam report.

=== DOMAIN ANALYSES ===
{domain_summary}

=== RAW SOURCE DATA ===
{raw_summary}

=== COMPRESSED TRANSCRIPTS ===
{transcript_summary}

=== TURN 1 SCAN OUTPUT ===
{json.dumps(seam_scan, indent=2)}

Produce the final contested narratives, coverage gaps, and key assumptions report. Output ONLY valid JSON."""


def _resolve_turn_model_config(
    base_model_config: dict | None, stage_cfg: dict | None, turn_name: str
) -> dict | None:
    if not base_model_config:
        return None

    turn_overrides = (stage_cfg or {}).get("turns", {}).get(turn_name, {})
    return {**base_model_config, **turn_overrides}


def _normalize_seam_scan(result: dict | None) -> dict:
    scan = dict(result or {})
    scan["schema_version"] = 1
    scan["tensions"] = scan.get("tensions", []) or []
    scan["absences"] = scan.get("absences", []) or []
    scan["assumptions"] = scan.get("assumptions", []) or []
    return scan


def _call_turn_json(
    prompt: str,
    user_content: str,
    model_config: dict | None,
    turn_name: str,
) -> dict:
    """Call a seams turn, retrying once without streaming on parse failures."""
    try:
        return call_llm(
            prompt,
            user_content,
            model_config,
            max_retries=1,
            json_mode=True,
            stream=True,
        )
    except Exception as exc:
        log.warning(f"seams: {turn_name} turn failed with streaming, retrying once: {exc}")
        return call_llm(
            prompt,
            user_content,
            model_config,
            max_retries=1,
            json_mode=True,
            stream=False,
        )


def _empty_seam_result() -> dict:
    return {
        "seam_scan": {
            "schema_version": 1,
            "tensions": [],
            "absences": [],
            "assumptions": [],
        },
        "seam_data": {
            "contested_narratives": [],
            "coverage_gaps": [],
            "key_assumptions": [],
            "seam_count": 0,
            "quiet_day": True,
        },
    }


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Detect narrative seams, coverage gaps, and key assumptions."""
    domain_analysis = context.get("domain_analysis", {})
    raw_sources = context.get("raw_sources", {})
    compressed_transcripts = context.get("compressed_transcripts", [])

    # Development default: keep seams on MiniMax to control iteration cost.
    effective_config = model_config or config.get("llm", {}).get(
        "seam_detection",
        {
            "provider": "fireworks",
            "model": "accounts/fireworks/models/minimax-m2p7",
            "max_tokens": 5000,
            "temperature": 0.3,
        },
    )
    stage_cfg = kwargs.get("stage_cfg") or {}
    scan_config = _resolve_turn_model_config(effective_config, stage_cfg, "scan")
    synthesis_config = _resolve_turn_model_config(
        effective_config, stage_cfg, "synthesis"
    )

    # Build the comprehensive user prompt
    domain_summary = _build_domain_summary(domain_analysis)
    raw_summary = _build_raw_source_summary(raw_sources)
    transcript_summary = _build_transcript_summary(compressed_transcripts)

    try:
        log.info("Stage: seams — running Turn 1 scan...")
        seam_scan = _call_turn_json(
            _SCAN_PROMPT,
            _scan_user_content(domain_summary, raw_summary, transcript_summary),
            scan_config,
            "scan",
        )
        seam_scan = _normalize_seam_scan(seam_scan)

        log.info("Stage: seams — running Turn 2 synthesis...")
        result = _call_turn_json(
            _SYNTHESIS_PROMPT,
            _synthesis_user_content(
                domain_summary,
                raw_summary,
                transcript_summary,
                seam_scan,
            ),
            synthesis_config,
            "synthesis",
        )

        # Validate output schema and URLs against known sources
        result = validate_stage_output(result, raw_sources, "seams")

        # Ensure all expected fields exist with safe defaults
        if "contested_narratives" not in result:
            result["contested_narratives"] = []
        if "coverage_gaps" not in result:
            result["coverage_gaps"] = []
        if "key_assumptions" not in result:
            result["key_assumptions"] = []

        cn = result.get("contested_narratives", [])
        cg = result.get("coverage_gaps", [])
        ka = result.get("key_assumptions", [])
        total = len(cn) + len(cg) + len(ka)
        result["seam_count"] = total
        if "quiet_day" not in result:
            result["quiet_day"] = total <= 1

        log.info(
            f"  Seam detection: {len(cn)} contested narratives, "
            f"{len(cg)} coverage gaps, {len(ka)} key assumptions"
        )
        return {"seam_scan": seam_scan, "seam_data": result}

    except Exception as e:
        log.warning(f"Seam detection failed (non-fatal): {e}")
        return _empty_seam_result()
