"""Prompt construction for the cross-domain stage."""

import json

from utils.prompts import load_prompt

_PLAN_PROMPT = load_prompt("cross_domain_plan.md")
_EXECUTE_PROMPT = load_prompt("cross_domain_execute.md")
_SYSTEM_PROMPT = _EXECUTE_PROMPT


def plan_prompt(deep_dive_count: int, worth_reading_count: int, connection_count: int) -> str:
    """Load the planning prompt with current digest sizing."""
    return load_prompt(
        "cross_domain_plan.md",
        {
            "deep_dive_count": deep_dive_count,
            "worth_reading_count": worth_reading_count,
            "connection_count": connection_count,
        },
    )


def execute_prompt(deep_dive_count: int, worth_reading_count: int) -> str:
    """Load the execution prompt with current digest sizing."""
    return load_prompt(
        "cross_domain_execute.md",
        {
            "deep_dive_count": deep_dive_count,
            "worth_reading_count": worth_reading_count,
        },
    )


def _build_input(
    domain_analysis: dict,
    seam_data: dict,
    raw_sources: dict,
    previous_cross_domain: dict | None = None,
) -> str:
    """Build the user content for the cross-domain synthesis prompt."""
    parts = []

    parts.append("=== DOMAIN ANALYSES ===")
    for domain_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        items = domain_result.get("items", [])
        parts.append(f"\n--- {domain_key.upper()} ({len(items)} items) ---")
        parts.append(json.dumps(domain_result, indent=2))

    parts.append("\n=== SEAM DETECTION RESULTS ===")
    parts.append(json.dumps(seam_data, indent=2))

    rss = raw_sources.get("rss", [])
    if rss:
        parts.append("\n=== SOURCE URL REFERENCE ===")
        parts.append("(Available URLs for linking — use only these)")
        for item in rss:
            if item.get("url"):
                parts.append(f"  {item.get('source', '?')}: {item.get('url', '')}")

    if previous_cross_domain:
        prev_glance_headlines = [
            i.get("headline", "")
            for i in previous_cross_domain.get("at_a_glance", [])
            if i.get("headline")
        ]
        prev_dive_headlines = [
            d.get("headline", "")
            for d in previous_cross_domain.get("deep_dives", [])
            if d.get("headline")
        ]
        if prev_glance_headlines or prev_dive_headlines:
            parts.append(
                "\n=== CONTINUITY — Yesterday's digest included these stories ==="
            )
            if prev_glance_headlines:
                parts.append("At a glance: " + " | ".join(prev_glance_headlines))
            if prev_dive_headlines:
                parts.append("Deep dives: " + " | ".join(prev_dive_headlines))
            parts.append(
                "If any of today's stories are developments in these ongoing narratives, note "
                '"continuing from yesterday" or "new development" in your analysis field. '
                "Do NOT repeat yesterday's analysis — just acknowledge the thread. "
                "If none of today's stories connect to yesterday, ignore this section entirely."
            )

    parts.append(
        "\n=== WORTH READING ===\n"
        "Prioritize substantial long-form pieces from the source data that reward slow reading "
        "over incremental breaking news. Include a worth_reading section in the final output."
    )

    return "\n".join(parts)


def _plan_user_content(
    domain_analysis: dict,
    seam_data: dict,
    raw_sources: dict,
    previous_cross_domain: dict | None = None,
) -> str:
    base = _build_input(domain_analysis, seam_data, raw_sources, previous_cross_domain)
    return (
        f"{base}\n\n"
        "Build the editorial plan: select the strongest cross-domain connections, "
        "choose the deep dives, choose worth-reading pieces, and record rejected alternatives. "
        "Output ONLY valid JSON."
    )


def _execute_user_content(
    domain_analysis: dict,
    seam_data: dict,
    raw_sources: dict,
    cross_domain_plan: dict,
    previous_cross_domain: dict | None = None,
) -> str:
    base = _build_input(domain_analysis, seam_data, raw_sources, previous_cross_domain)
    return (
        f"{base}\n\n=== EDITORIAL PLAN ===\n"
        f"{json.dumps(cross_domain_plan, indent=2)}\n\n"
        "Execute the plan into the final cross-domain digest output. "
        "Output ONLY valid JSON."
    )
