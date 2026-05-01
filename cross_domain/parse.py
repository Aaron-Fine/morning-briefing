"""Normalization and fallback helpers for the cross-domain stage."""

import logging

from utils.urls import collect_known_urls, registered_domain, url_known

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

_DEFAULT_PRIMARY_GLANCE_TAGS = ("war", "ai", "defense")
_DEFAULT_PRIMARY_DOMAIN_TAGS = {
    "geopolitics": "war",
    "ai_tech": "ai",
    "defense_space": "defense",
}
_DEFAULT_DEPTH_PRIORITY = {"widely-reported": 0, "corroborated": 1, "single-source": 2}


def _cross_domain_cfg(config: dict | None) -> dict:
    return (config or {}).get("cross_domain", {}) or {}


def _glance_cfg(config: dict | None) -> dict:
    return _cross_domain_cfg(config).get("at_a_glance", {}) or {}


def _primary_glance_tags(config: dict | None) -> tuple[str, ...]:
    raw = _glance_cfg(config).get("primary_tags", _DEFAULT_PRIMARY_GLANCE_TAGS)
    return tuple(str(tag).strip() for tag in raw if str(tag).strip())


def _primary_domain_tags(config: dict | None) -> dict[str, str]:
    raw = _glance_cfg(config).get("primary_domain_tags", _DEFAULT_PRIMARY_DOMAIN_TAGS)
    if not isinstance(raw, dict):
        return dict(_DEFAULT_PRIMARY_DOMAIN_TAGS)
    return {str(k): str(v) for k, v in raw.items()}


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


def _source_names(item: dict) -> set[str]:
    """Return normalized outlet labels used by source-distribution diagnostics."""
    names = set()
    for link in item.get("links") or []:
        if not isinstance(link, dict):
            continue
        label = str(link.get("label", "")).strip()
        if not label:
            continue
        names.add(label.split(":", 1)[0].strip() if ":" in label else label)
    return names


def _would_exceed_source_cap(
    item: dict, source_counts: dict[str, int], max_per_source: int
) -> bool:
    return any(
        source_counts.get(source, 0) >= max_per_source
        for source in _source_names(item)
    )


def _add_selected_item(
    selected: set[int],
    source_counts: dict[str, int],
    ranked_index: int,
    item: dict,
) -> None:
    selected.add(ranked_index)
    for source in _source_names(item):
        source_counts[source] = source_counts.get(source, 0) + 1


def _cap_at_a_glance_items(
    items: list[dict], max_items: int, config: dict | None = None
) -> list[dict]:
    """Cap at-a-glance items while preserving topic and outlet diversity.

    The LLM often returns more candidates than the email should show. A pure
    source-depth sort can accidentally drop all AI coverage or keep too many
    items from one outlet. This selector keeps the same ranking inputs but adds
    deterministic diversity constraints before falling back to fill the cap.
    """
    if len(items) <= max_items:
        return items

    glance_cfg = _glance_cfg(config)
    depth_priority = glance_cfg.get("depth_priority", _DEFAULT_DEPTH_PRIORITY)
    if not isinstance(depth_priority, dict):
        depth_priority = _DEFAULT_DEPTH_PRIORITY
    ranked = sorted(
        enumerate(items),
        key=lambda pair: (
            depth_priority.get(pair[1].get("source_depth", ""), 3),
            0 if pair[1].get("cross_domain_note") else 1,
            pair[0],
        ),
    )

    selected: set[int] = set()
    source_counts: dict[str, int] = {}
    max_source_share = float(glance_cfg.get("max_source_share", 0.4))
    max_per_source = max(1, int(max_items * max_source_share))
    available_tags = {item.get("tag", "") for _, item in ranked}

    for tag in _primary_glance_tags(config):
        if tag not in available_tags or len(selected) >= max_items:
            continue

        fallback: tuple[int, dict] | None = None
        for ranked_index, item in ranked:
            if ranked_index in selected or item.get("tag", "") != tag:
                continue
            if fallback is None:
                fallback = (ranked_index, item)
            if not _would_exceed_source_cap(item, source_counts, max_per_source):
                _add_selected_item(selected, source_counts, ranked_index, item)
                fallback = None
                break
        if fallback is not None:
            _add_selected_item(selected, source_counts, fallback[0], fallback[1])

    for ranked_index, item in ranked:
        if len(selected) >= max_items:
            break
        if ranked_index in selected:
            continue
        if _would_exceed_source_cap(item, source_counts, max_per_source):
            continue
        _add_selected_item(selected, source_counts, ranked_index, item)

    for ranked_index, item in ranked:
        if len(selected) >= max_items:
            break
        if ranked_index not in selected:
            _add_selected_item(selected, source_counts, ranked_index, item)

    return [item for ranked_index, item in ranked if ranked_index in selected]


def _item_signature(item: dict) -> tuple:
    urls = tuple(
        sorted(
            str(link.get("url", "")).strip()
            for link in item.get("links") or []
            if isinstance(link, dict) and link.get("url")
        )
    )
    return (item.get("item_id", ""), urls, item.get("headline", ""))


def _fallback_glance_item(item: dict, tag: str) -> dict:
    entry = dict(item)
    entry["item_id"] = item.get("item_id", "")
    entry["tag"] = tag
    entry["tag_label"] = _TAG_LABELS[tag]
    entry["headline"] = str(item.get("headline", "")).strip()
    entry["facts"] = str(item.get("facts", ""))
    entry["analysis"] = str(item.get("analysis", ""))
    entry["source_depth"] = item.get("source_depth", "single-source")
    entry["cross_domain_note"] = None
    entry["links"] = list(item.get("links", []) or [])
    entry["connection_hooks"] = list(item.get("connection_hooks", []) or [])
    return entry


def _ensure_primary_glance_coverage(
    items: list[dict], domain_analysis: dict, config: dict | None = None
) -> list[dict]:
    """Add the best available primary-desk item when execution omits a primary tag."""
    primary_tags = _primary_glance_tags(config)
    present_tags = {item.get("tag", "") for item in items}
    if all(tag in present_tags for tag in primary_tags):
        return items

    existing_signatures = {_item_signature(item) for item in items}
    additions = []
    for domain_key, tag in _primary_domain_tags(config).items():
        if tag in present_tags:
            continue
        domain_result = domain_analysis.get(domain_key, {})
        if not isinstance(domain_result, dict):
            continue
        for candidate in domain_result.get("items", []) or []:
            if not isinstance(candidate, dict) or candidate.get("deep_dive_candidate"):
                continue
            addition = _fallback_glance_item(candidate, tag)
            signature = _item_signature(addition)
            if signature in existing_signatures:
                break
            additions.append(addition)
            existing_signatures.add(signature)
            present_tags.add(tag)
            break

    if additions:
        log.info(
            "  cross_domain: added %s primary-coverage at-a-glance fallback item(s)",
            len(additions),
        )
    return [*items, *additions]


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
    raw_sources: dict | None = None,
    config: dict | None = None,
) -> dict:
    """Return the full cross-domain artifact contract for fallback paths."""
    output = _empty_output(domain_analysis)
    if config is not None:
        output = _validated_output(output, domain_analysis, raw_sources or {}, config)

    return {
        "cross_domain_plan": cross_domain_plan or _empty_cross_domain_plan(),
        "cross_domain_output": output,
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


def _distinct_domains(links: list[dict]) -> set[str]:
    domains = set()
    for lnk in links:
        domain = registered_domain(lnk.get("url", ""))
        if domain:
            domains.add(domain)
    return domains


def _recompute_source_depth(item: dict) -> str:
    """Recompute source_depth from distinct registered domains in links.

    Overrides LLM-provided depth labels when same-outlet evidence dominates.
    """
    links = item.get("links", [])
    if not links:
        return "single-source"
    domains = _distinct_domains(links)
    if len(domains) >= 4:
        return "widely-reported"
    if len(domains) >= 2:
        return "corroborated"
    return "single-source"


def _downgrade_same_outlet_depth(result: dict) -> dict:
    """Recompute source_depth for all items; record downgrades in metadata."""
    downgrades = []
    for item in result.get("at_a_glance", []):
        original = item.get("source_depth", "")
        recomputed = _recompute_source_depth(item)
        if original and original != recomputed:
            downgrades.append(
                {
                    "item_id": item.get("item_id", ""),
                    "section": "at_a_glance",
                    "original_depth": original,
                    "recomputed_depth": recomputed,
                    "domains": sorted(_distinct_domains(item.get("links", []))),
                }
            )
        item["source_depth"] = recomputed

    for dive in result.get("deep_dives", []):
        original = dive.get("source_depth", "")
        recomputed = _recompute_source_depth(dive)
        if original and original != recomputed:
            downgrades.append(
                {
                    "item_id": dive.get("headline", "")[:40],
                    "section": "deep_dives",
                    "original_depth": original,
                    "recomputed_depth": recomputed,
                    "domains": sorted(_distinct_domains(dive.get("further_reading", []))),
                }
            )
        dive["source_depth"] = recomputed

    if downgrades:
        log.warning(
            f"cross_domain: downgraded {len(downgrades)} source_depth label(s) "
            f"due to same-outlet concentration"
        )
    result["_source_depth_downgrades"] = downgrades
    return result


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

    result["at_a_glance"] = _ensure_primary_glance_coverage(
        result["at_a_glance"], domain_analysis, config
    )
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

    # Recompute source_depth from distinct domains before enforcing caps
    result = _downgrade_same_outlet_depth(result)

    digest_cfg = config.get("digest", {})
    glance_cfg = digest_cfg.get("at_a_glance", {})
    max_items = glance_cfg.get("max_items", 7)
    if len(result["at_a_glance"]) > max_items:
        original_count = len(result["at_a_glance"])
        result["at_a_glance"] = _cap_at_a_glance_items(
            result["at_a_glance"], max_items, config
        )
        log.info(
            f"  cross_domain: capped at_a_glance from {original_count} "
            f"to {len(result['at_a_glance'])} items "
            f"(dropped {original_count - len(result['at_a_glance'])} "
            "lower-priority/diversity-constrained items)"
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
