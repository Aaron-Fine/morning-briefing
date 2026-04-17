"""Stage: briefing_packet — Build compressed briefing packet for follow-up chat.

Assembles all pipeline artifacts into a single structured JSON file optimized
for use as context in a follow-up conversation with an LLM. Target: 30,000 tokens.

Also writes to output/latest_briefing_packet.json for easy access.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_TARGET_TOKENS = 30_000

# Drop priority for compression (lowest priority first)
_DROP_PRIORITY = ["perspective-diversity", "global-south", "econ-trade"]


def _token_estimate(s: str) -> int:
    return len(s) // 4


def _first_two_sentences(text: str) -> str:
    """Return approximately the first two sentences of text."""
    if not text:
        return ""
    parts = text.split(". ")
    return ". ".join(parts[:2]) + ("." if len(parts) > 2 else "")


def _build_source_index(raw_sources: dict, domain_analysis: dict) -> list:
    """Build source index from rss items, including full summary for referenced items."""
    # Collect all URLs referenced in domain analysis
    referenced_urls: set[str] = set()
    for domain_result in domain_analysis.values():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []):
            for link in item.get("links", []):
                if link.get("url"):
                    referenced_urls.add(link["url"])

    index = []
    for item in raw_sources.get("rss", []):
        url = item.get("url", "")
        summary = item.get("summary", "") or item.get("content", "") or ""
        is_referenced = url in referenced_urls
        index.append({
            "title": item.get("title", ""),
            "source": item.get("source", "") or item.get("name", ""),
            "category": item.get("category", ""),
            "reliability": item.get("reliability", ""),
            "url": url,
            "summary": summary if is_referenced else _first_two_sentences(summary),
            "_referenced": is_referenced,
            "_category": item.get("category", ""),
        })

    return index


def _build_transcript_summaries(raw_sources: dict) -> list:
    """Build transcript summaries from analysis transcripts."""
    summaries = []
    for t in raw_sources.get("analysis_transcripts", []):
        summaries.append({
            "channel": t.get("channel", "") or t.get("name", ""),
            "title": t.get("title", ""),
            "summary": t.get("summary", "") or t.get("content", ""),
        })
    return summaries


def _build_connection_hooks(domain_analysis: dict) -> list:
    """Collect and deduplicate connection_hooks across all domain analysis items."""
    seen: set[tuple] = set()
    hooks = []
    for domain_result in domain_analysis.values():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []):
            for hook in item.get("connection_hooks", []):
                key = (
                    hook.get("entity", ""),
                    hook.get("region", ""),
                    hook.get("theme", ""),
                    hook.get("policy", ""),
                )
                if key not in seen:
                    seen.add(key)
                    hooks.append(hook)
    return hooks


def _build_metadata(context: dict, config: dict) -> dict:
    """Build metadata section from run_meta and config."""
    run_meta = context.get("run_meta", {})
    raw_sources = context.get("raw_sources", {})

    source_counts: dict[str, int] = {}
    for item in raw_sources.get("rss", []):
        cat = item.get("category", "unknown")
        source_counts[cat] = source_counts.get(cat, 0) + 1
    source_counts["transcripts"] = len(raw_sources.get("analysis_transcripts", []))

    models_used: dict[str, str] = {}
    for stage in config.get("pipeline", {}).get("stages", []):
        model_cfg = stage.get("model")
        if model_cfg and model_cfg.get("model"):
            models_used[stage["name"]] = model_cfg["model"]

    return {
        "date": run_meta.get("run_date", datetime.now().strftime("%Y-%m-%d")),
        "source_counts": source_counts,
        "models_used": models_used,
        "stage_timings": run_meta.get("stage_timings", {}),
        "stage_failures": run_meta.get("stage_failures", []),
    }


def _compress_to_budget(packet: dict) -> dict:
    """Apply compression steps until packet is under _TARGET_TOKENS."""
    estimate = _token_estimate(json.dumps(packet, default=str))
    if estimate <= _TARGET_TOKENS:
        return packet

    # Step 1: Truncate non-referenced source summaries to 2 sentences
    for item in packet.get("source_index", []):
        if not item.get("_referenced", False):
            item["summary"] = _first_two_sentences(item.get("summary", ""))
    estimate = _token_estimate(json.dumps(packet, default=str))
    if estimate <= _TARGET_TOKENS:
        return packet

    # Step 2: Drop source_index entries by category, lowest priority first
    for cat in _DROP_PRIORITY:
        packet["source_index"] = [
            i for i in packet.get("source_index", [])
            if i.get("_category", "") != cat
        ]
        estimate = _token_estimate(json.dumps(packet, default=str))
        if estimate <= _TARGET_TOKENS:
            return packet

    # Step 3: Truncate transcript summaries to 500 chars each
    for t in packet.get("transcript_summaries", []):
        if len(t.get("summary", "")) > 500:
            t["summary"] = t["summary"][:500] + "…"
    estimate = _token_estimate(json.dumps(packet, default=str))
    if estimate <= _TARGET_TOKENS:
        return packet

    # Step 4: Truncate domain analysis items to facts + headline only
    for domain_result in packet.get("domain_analyses", {}).values():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []):
            item.pop("analysis", None)

    return packet


def run(context: dict, config: dict, model_config=None, **kwargs) -> dict:
    """Build compressed briefing packet for follow-up chat interface."""
    cross_domain_output = context.get("cross_domain_output", {})
    domain_analysis = context.get("domain_analysis", {})
    raw_sources = context.get("raw_sources", {})
    seam_data = context.get("seam_data", {})
    run_date = datetime.now().strftime("%Y-%m-%d")

    digest_summary = {
        "date": run_date,
        "at_a_glance_headlines": [
            i.get("headline", "") for i in cross_domain_output.get("at_a_glance", [])
        ],
        "deep_dive_headlines": [
            d.get("headline", "") for d in cross_domain_output.get("deep_dives", [])
        ],
    }

    source_index = _build_source_index(raw_sources, domain_analysis)
    transcript_summaries = _build_transcript_summaries(raw_sources)
    connection_hooks = _build_connection_hooks(domain_analysis)
    metadata = _build_metadata(context, config)

    packet = {
        "digest_summary": digest_summary,
        "source_index": source_index,
        "transcript_summaries": transcript_summaries,
        "domain_analyses": domain_analysis,
        "seam_data": seam_data,
        "connection_hooks": connection_hooks,
        "key_assumptions": seam_data.get("key_assumptions", []),
        "metadata": metadata,
    }

    packet = _compress_to_budget(packet)

    # Clean up internal-only fields
    for item in packet.get("source_index", []):
        item.pop("_referenced", None)
        item.pop("_category", None)

    estimated_tokens = _token_estimate(json.dumps(packet, default=str))
    log.info(
        f"briefing_packet: built packet — "
        f"{len(source_index)} sources, "
        f"{len(transcript_summaries)} transcripts, "
        f"~{estimated_tokens:,} tokens estimated"
    )

    # Write to latest_briefing_packet.json for easy access
    latest_path = _ROOT / "output" / "latest_briefing_packet.json"
    try:
        latest_path.parent.mkdir(exist_ok=True)
        latest_path.write_text(json.dumps(packet, indent=2, default=str), encoding="utf-8")
        log.info(f"briefing_packet: wrote {latest_path}")
    except Exception as e:
        log.warning(f"briefing_packet: failed to write latest_briefing_packet.json: {e}")

    return {"briefing_packet": packet}
