"""Stage: cross_domain — Editor-in-chief cross-domain synthesis pass.

This is the highest-order analytical stage in the pipeline. It reads all domain
analyses and seam data, discovers cross-domain connections the specialist desks
couldn't see from within their domains, selects and writes deep dives, and
produces the final editorial product.

The cross-domain stage does NOT rewrite domain analysis work. It:
  1. Discovers connections across domains via connection_hooks matching.
  2. Selects 1-3 deep dives from candidates flagged by domain passes.
  3. Writes deep dive body text that goes deeper than at-a-glance items.
  4. Adds cross_domain_note to at-a-glance items with multi-domain relevance.
  5. Enforces deduplication: each story appears in at most two sections.

Model selection: Best available model. This is the one stage where model quality
directly determines digest quality.

Inputs:  domain_analysis (dict), seam_data (dict), raw_sources (dict)
Outputs: cross_domain_output (dict) containing at_a_glance, deep_dives,
         cross_domain_connections, market_context
"""

import json
import logging

from morning_digest.llm import call_llm
from utils.prompts import load_prompt
from utils.urls import collect_known_urls, url_known
from morning_digest.validate import validate_stage_output

log = logging.getLogger(__name__)

_VALID_TAGS = {
    "war",
    "domestic",
    "econ",
    "ai",
    "tech",
    "defense",
    "space",
    "cyber",
    "local",
    "science",
    "energy",
    "biotech",
}

_TAG_LABELS = {
    "war": "Conflict",
    "domestic": "Politics",
    "econ": "Economy",
    "ai": "AI",
    "tech": "Technology",
    "defense": "Defense",
    "space": "Space",
    "cyber": "Cyber",
    "local": "Local",
    "science": "Science",
    "energy": "Energy",
    "biotech": "Biotech",
}

# Keyword → standard tag mapping for post-processing normalization.
# Keys are lowercase substrings; first match wins.
_TAG_KEYWORDS: list[tuple[str, str]] = [
    # war / conflict
    ("iran", "war"),
    ("israel", "war"),
    ("ukraine", "war"),
    ("russia", "war"),
    ("military", "war"),
    ("combat", "war"),
    ("war", "war"),
    ("conflict", "war"),
    ("attack", "war"),
    ("strike", "war"),
    ("missile", "war"),
    ("troops", "war"),
    ("ceasefire", "war"),
    ("nato", "war"),
    ("hormuz", "war"),
    ("hostage", "war"),
    # defense
    ("defense", "defense"),
    ("pentagon", "defense"),
    ("f-35", "defense"),
    ("f-15", "defense"),
    ("procurement", "defense"),
    ("dod", "defense"),
    ("special forces", "defense"),
    ("recovery", "defense"),
    ("basing", "defense"),
    # space
    ("space", "space"),
    ("lunar", "space"),
    ("orbit", "space"),
    ("satellite", "space"),
    ("cislunar", "space"),
    ("launch", "space"),
    ("nasa", "space"),
    # ai
    ("ai", "ai"),
    ("llm", "ai"),
    ("artificial intelligence", "ai"),
    ("machine learning", "ai"),
    ("openai", "ai"),
    ("anthropic", "ai"),
    ("developer", "ai"),
    ("tooling", "ai"),
    ("model", "ai"),
    # tech
    ("tech", "tech"),
    ("software", "tech"),
    ("open source", "tech"),
    ("github", "tech"),
    # cyber
    ("cyber", "cyber"),
    ("hack", "cyber"),
    ("security breach", "cyber"),
    ("ransomware", "cyber"),
    ("malware", "cyber"),
    # econ
    ("econ", "econ"),
    ("market", "econ"),
    ("trade", "econ"),
    ("tariff", "econ"),
    ("inflation", "econ"),
    ("fed", "econ"),
    ("gdp", "econ"),
    ("labor", "econ"),
    ("wage", "econ"),
    ("food", "econ"),
    ("supply chain", "econ"),
    ("wto", "econ"),
    ("imf", "econ"),
    # energy
    ("energy", "energy"),
    ("oil", "energy"),
    ("gas", "energy"),
    ("grid", "energy"),
    ("utility", "energy"),
    ("mining", "energy"),
    ("critical mineral", "energy"),
    ("lithium", "energy"),
    ("solar", "energy"),
    ("wind power", "energy"),
    ("nuclear power", "energy"),
    ("electricity", "energy"),
    # biotech
    ("biotech", "biotech"),
    ("pharmaceutical", "biotech"),
    ("drug approval", "biotech"),
    ("clinical trial", "biotech"),
    ("gene therapy", "biotech"),
    ("crispr", "biotech"),
    ("vaccine", "biotech"),
    ("fda", "biotech"),
    ("nih", "biotech"),
    # science
    ("science", "science"),
    ("climate", "science"),
    ("research", "science"),
    ("study", "science"),
    ("discovery", "science"),
    ("experiment", "science"),
    ("peer-reviewed", "science"),
    # local
    ("local", "local"),
    ("utah", "local"),
    ("cache valley", "local"),
    ("logan", "local"),
    ("community", "local"),
    ("municipal", "local"),
    ("county", "local"),
    # domestic / politics
    ("trump", "domestic"),
    ("congress", "domestic"),
    ("senate", "domestic"),
    ("white house", "domestic"),
    ("election", "domestic"),
    ("domestic", "domestic"),
    ("administration", "domestic"),
    ("politics", "domestic"),
    ("gop", "domestic"),
]


def _normalize_tag(raw: str) -> str:
    """Map a raw LLM tag to the standard CSS vocabulary.

    Tries exact match first, then keyword scan, then falls back to 'domestic'.
    """
    normalized = raw.strip().lower()
    if normalized in _VALID_TAGS:
        return normalized
    for keyword, tag in _TAG_KEYWORDS:
        if keyword in normalized:
            return tag
    log.debug(f"cross_domain: unknown tag '{raw}' — defaulting to 'domestic'")
    return "domestic"


_PLAN_PROMPT = load_prompt("cross_domain_plan.md")
_EXECUTE_PROMPT = load_prompt("cross_domain_execute.md")
_SYSTEM_PROMPT = _EXECUTE_PROMPT


def _build_input(
    domain_analysis: dict,
    seam_data: dict,
    raw_sources: dict,
    previous_cross_domain: dict | None = None,
) -> str:
    """Build the user content for the cross-domain synthesis prompt."""
    parts = []

    # Domain analyses
    parts.append("=== DOMAIN ANALYSES ===")
    for domain_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        items = domain_result.get("items", [])
        parts.append(f"\n--- {domain_key.upper()} ({len(items)} items) ---")
        parts.append(json.dumps(domain_result, indent=2))

    # Seam data
    parts.append("\n=== SEAM DETECTION RESULTS ===")
    parts.append(json.dumps(seam_data, indent=2))

    # Raw source URLs for reference (just titles + URLs, not full summaries)
    rss = raw_sources.get("rss", [])
    if rss:
        parts.append("\n=== SOURCE URL REFERENCE ===")
        parts.append("(Available URLs for linking — use only these)")
        for item in rss:
            if item.get("url"):
                parts.append(f"  {item.get('source', '?')}: {item.get('url', '')}")

    # Previous-day continuity
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


def _resolve_turn_model_config(
    base_model_config: dict | None, stage_cfg: dict | None, turn_name: str
) -> dict | None:
    if not base_model_config:
        return None

    turn_overrides = (stage_cfg or {}).get("turns", {}).get(turn_name, {})
    return {**base_model_config, **turn_overrides}


def _normalize_cross_domain_plan(
    result: dict | None,
    *,
    deep_dive_count: int,
    worth_reading_count: int,
    connection_count: int,
) -> dict:
    plan = dict(result or {})
    plan["schema_version"] = 1
    plan["cross_domain_connections"] = (
        list(plan.get("cross_domain_connections", []) or [])[:connection_count]
    )
    plan["deep_dives"] = list(plan.get("deep_dives", []) or [])[:deep_dive_count]
    plan["worth_reading"] = (
        list(plan.get("worth_reading", []) or [])[:worth_reading_count]
    )
    plan["rejected_alternatives"] = list(plan.get("rejected_alternatives", []) or [])
    if "planning_scope" in plan and not isinstance(plan["planning_scope"], dict):
        plan.pop("planning_scope")
    plan.setdefault(
        "planning_scope",
        {
            "deep_dive_count": deep_dive_count,
            "worth_reading_count": worth_reading_count,
            "connection_count": connection_count,
        },
    )
    return plan


def _call_turn_json(
    prompt: str,
    user_content: str,
    model_config: dict | None,
    turn_name: str,
) -> dict:
    try:
        return call_llm(
            prompt,
            user_content,
            model_config,
            max_retries=2,
            json_mode=True,
            stream=True,
        )
    except Exception as exc:
        log.warning(
            f"cross_domain: {turn_name} turn failed with streaming, retrying once: {exc}"
        )
        return call_llm(
            prompt,
            user_content,
            model_config,
            max_retries=2,
            json_mode=True,
            stream=False,
        )


def _validated_output(
    result: dict,
    domain_analysis: dict,
    raw_sources: dict,
    config: dict,
) -> dict:
    result.setdefault("at_a_glance", [])
    result.setdefault("deep_dives", [])
    result.setdefault("cross_domain_connections", [])
    result.setdefault("worth_reading", [])
    if "market_context" not in result:
        econ = domain_analysis.get("econ", {})
        result["market_context"] = econ.get("market_context", "")

    known_urls = collect_known_urls(raw_sources, domain_analysis)

    for item in result["at_a_glance"]:
        item["tag"] = _normalize_tag(item.get("tag", ""))
        item["tag_label"] = _TAG_LABELS.get(item["tag"], item.get("tag_label", ""))

    for item in result["at_a_glance"]:
        item["links"] = [
            lnk
            for lnk in item.get("links", [])
            if url_known(lnk.get("url", ""), known_urls)
        ]
    for dive in result["deep_dives"]:
        dive["further_reading"] = [
            lnk
            for lnk in dive.get("further_reading", [])
            if url_known(lnk.get("url", ""), known_urls)
        ]
    for read in result["worth_reading"]:
        if not url_known(read.get("url", ""), known_urls):
            read["url"] = ""

    digest_cfg = config.get("digest", {})
    glance_cfg = digest_cfg.get("at_a_glance", {})
    max_items = glance_cfg.get("max_items", 7)
    if len(result["at_a_glance"]) > max_items:
        depth_priority = {"widely-reported": 0, "corroborated": 1, "single-source": 2}
        result["at_a_glance"].sort(
            key=lambda i: (
                depth_priority.get(i.get("source_depth", ""), 3),
                0 if i.get("cross_domain_note") else 1,
            )
        )
        dropped = result["at_a_glance"][max_items:]
        result["at_a_glance"] = result["at_a_glance"][:max_items]
        log.info(
            f"  cross_domain: capped at_a_glance from {max_items + len(dropped)} "
            f"to {max_items} items (dropped {len(dropped)} lower-priority items)"
        )

    return result


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Run cross-domain synthesis and return the editorial product."""
    domain_analysis = context.get("domain_analysis", {})
    seam_data = context.get("seam_data", {})
    raw_sources = context.get("raw_sources", {})

    effective_config = model_config or config.get("llm", {})
    stage_cfg = kwargs.get("stage_cfg") or {}
    plan_config = _resolve_turn_model_config(effective_config, stage_cfg, "plan")
    execute_config = _resolve_turn_model_config(effective_config, stage_cfg, "execute")

    digest_cfg = config.get("digest", {})
    deep_dive_count = digest_cfg.get("deep_dives", {}).get("count", 2)
    worth_reading_count = digest_cfg.get("worth_reading", {}).get("count", 3)
    connection_count = 3

    # Check if we have domain analysis to work with
    has_items = any(
        isinstance(v, dict) and v.get("items") for v in domain_analysis.values()
    )
    if not has_items:
        log.warning("cross_domain: no domain analysis items — returning passthrough")
        return {"cross_domain_output": _empty_output(domain_analysis)}

    try:
        cross_domain_plan = context.get("cross_domain_plan")
        if context.get("cross_domain_from_plan") and isinstance(cross_domain_plan, dict):
            log.info("Stage: cross_domain — reusing same-day cross_domain_plan")
        else:
            log.info("Stage: cross_domain — running Turn 1 planning...")
            cross_domain_plan = _call_turn_json(
                load_prompt(
                    "cross_domain_plan.md",
                    {
                        "deep_dive_count": deep_dive_count,
                        "worth_reading_count": worth_reading_count,
                        "connection_count": connection_count,
                    },
                ),
                _plan_user_content(
                    domain_analysis,
                    seam_data,
                    raw_sources,
                    context.get("previous_cross_domain"),
                ),
                plan_config,
                "plan",
            )
            cross_domain_plan = _normalize_cross_domain_plan(
                cross_domain_plan,
                deep_dive_count=deep_dive_count,
                worth_reading_count=worth_reading_count,
                connection_count=connection_count,
            )

        log.info("Stage: cross_domain — running Turn 2 execution...")
        result = _call_turn_json(
            load_prompt(
                "cross_domain_execute.md",
                {
                    "deep_dive_count": deep_dive_count,
                    "worth_reading_count": worth_reading_count,
                },
            ),
            _execute_user_content(
                domain_analysis,
                seam_data,
                raw_sources,
                cross_domain_plan,
                context.get("previous_cross_domain"),
            ),
            execute_config,
            "execute",
        )
    except Exception as e:
        log.error(f"cross_domain: LLM call failed: {e}")
        return {"cross_domain_output": _empty_output(domain_analysis)}

    # Normalize result
    if not isinstance(result, dict):
        log.warning("cross_domain: LLM returned non-dict, falling back to passthrough")
        return {"cross_domain_output": _empty_output(domain_analysis)}

    result = _validated_output(result, domain_analysis, raw_sources, config)
    result = validate_stage_output(
        result,
        raw_sources,
        "cross_domain",
        collect_diagnostics=True,
        domain_analysis=domain_analysis,
    )
    validation_diagnostics = result.pop(
        "_validation_diagnostics",
        {"stage": "cross_domain", "issue_count": 0, "issues": []},
    )

    n_glance = len(result["at_a_glance"])
    n_dives = len(result["deep_dives"])
    n_connections = len(result["cross_domain_connections"])
    log.info(
        f"  cross_domain: {n_glance} at-a-glance, {n_dives} deep dives, "
        f"{n_connections} cross-domain connections"
    )

    return {
        "cross_domain_plan": cross_domain_plan,
        "cross_domain_output": result,
        "validation_diagnostics": validation_diagnostics,
    }


def _empty_output(domain_analysis: dict) -> dict:
    """Build a passthrough output when cross-domain synthesis can't run.

    Falls back to the simple merge logic that assemble.py used in Phase 1.
    """
    all_items = []
    market_context = ""
    for domain_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        if domain_key == "econ" and domain_result.get("market_context"):
            market_context = domain_result["market_context"]
        for item in domain_result.get("items", []):
            all_items.append(item)

    # Separate deep dive candidates
    at_a_glance = [i for i in all_items if not i.get("deep_dive_candidate")]
    dive_candidates = [i for i in all_items if i.get("deep_dive_candidate")]

    # Simple deep dive conversion
    deep_dives = []
    for item in dive_candidates[:3]:
        body_parts = []
        if item.get("facts"):
            body_parts.append(f"<p>{item['facts']}</p>")
        if item.get("analysis"):
            body_parts.append(f"<p>{item['analysis']}</p>")
        if item.get("deep_dive_rationale"):
            body_parts.append(
                f"<p><em>Why this matters: {item['deep_dive_rationale']}</em></p>"
            )
        deep_dives.append(
            {
                "headline": item.get("headline", ""),
                "body": "\n".join(body_parts),
                "further_reading": item.get("links", []),
                "source_depth": item.get("source_depth", ""),
                "domains_bridged": [],
            }
        )

    return {
        "at_a_glance": at_a_glance,
        "deep_dives": deep_dives,
        "cross_domain_connections": [],
        "market_context": market_context,
        "worth_reading": [],
    }
