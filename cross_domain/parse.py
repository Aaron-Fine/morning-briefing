"""Normalization and fallback helpers for the cross-domain stage."""

import logging

from utils.urls import collect_known_urls, url_known

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

_TAG_KEYWORDS: list[tuple[str, str]] = [
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
    ("defense", "defense"),
    ("pentagon", "defense"),
    ("f-35", "defense"),
    ("f-15", "defense"),
    ("procurement", "defense"),
    ("dod", "defense"),
    ("special forces", "defense"),
    ("recovery", "defense"),
    ("basing", "defense"),
    ("space", "space"),
    ("lunar", "space"),
    ("orbit", "space"),
    ("satellite", "space"),
    ("cislunar", "space"),
    ("launch", "space"),
    ("nasa", "space"),
    ("ai", "ai"),
    ("llm", "ai"),
    ("artificial intelligence", "ai"),
    ("machine learning", "ai"),
    ("openai", "ai"),
    ("anthropic", "ai"),
    ("developer", "ai"),
    ("tooling", "ai"),
    ("model", "ai"),
    ("tech", "tech"),
    ("software", "tech"),
    ("open source", "tech"),
    ("github", "tech"),
    ("cyber", "cyber"),
    ("hack", "cyber"),
    ("security breach", "cyber"),
    ("ransomware", "cyber"),
    ("malware", "cyber"),
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
    ("biotech", "biotech"),
    ("pharmaceutical", "biotech"),
    ("drug approval", "biotech"),
    ("clinical trial", "biotech"),
    ("gene therapy", "biotech"),
    ("crispr", "biotech"),
    ("vaccine", "biotech"),
    ("fda", "biotech"),
    ("nih", "biotech"),
    ("science", "science"),
    ("climate", "science"),
    ("research", "science"),
    ("study", "science"),
    ("discovery", "science"),
    ("experiment", "science"),
    ("peer-reviewed", "science"),
    ("local", "local"),
    ("utah", "local"),
    ("cache valley", "local"),
    ("logan", "local"),
    ("community", "local"),
    ("municipal", "local"),
    ("county", "local"),
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
    """Map a raw LLM tag to the standard CSS vocabulary."""
    normalized = raw.strip().lower()
    if normalized in _VALID_TAGS:
        return normalized
    for keyword, tag in _TAG_KEYWORDS:
        if keyword in normalized:
            return tag
    log.debug(f"cross_domain: unknown tag '{raw}' — defaulting to 'domestic'")
    return "domestic"


def _empty_cross_domain_plan() -> dict:
    """Return the minimal persisted plan shape for fallback paths."""
    return {
        "schema_version": 1,
        "cross_domain_connections": [],
        "deep_dives": [],
        "worth_reading": [],
        "rejected_alternatives": [],
    }


def _fallback_validation_diagnostics(reason: str, message: str = "") -> dict:
    """Return explicit diagnostics when validation did not run on LLM output."""
    issue = {
        "kind": "cross_domain_fallback",
        "reason": reason,
    }
    if message:
        issue["message"] = message
    return {
        "stage": "cross_domain",
        "issue_count": 1,
        "issues": [issue],
    }


def _fallback_outputs(
    domain_analysis: dict,
    cross_domain_plan: dict | None = None,
    *,
    reason: str,
    message: str = "",
    contract_issues: list[dict] | None = None,
) -> dict:
    """Return the full cross-domain artifact contract for fallback paths."""
    return {
        "cross_domain_plan": cross_domain_plan or _empty_cross_domain_plan(),
        "cross_domain_output": _empty_output(domain_analysis),
        "validation_diagnostics": _fallback_validation_diagnostics(reason, message),
        "cross_domain_contract_issues": contract_issues or [],
    }


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


def _empty_output(domain_analysis: dict) -> dict:
    """Build a passthrough output when cross-domain synthesis can't run."""
    all_items = []
    market_context = ""
    for domain_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        if domain_key == "econ" and domain_result.get("market_context"):
            market_context = domain_result["market_context"]
        for item in domain_result.get("items", []):
            all_items.append(item)

    at_a_glance = [i for i in all_items if not i.get("deep_dive_candidate")]
    dive_candidates = [i for i in all_items if i.get("deep_dive_candidate")]

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
