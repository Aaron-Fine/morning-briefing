"""Stage: assemble — Merge all stage outputs and render the HTML digest.

Supports two pipeline configurations:
  Phase 3+: cross_domain_output present → use editor-in-chief output
  Phase 1:  domain_analysis present → merge domain artifacts into template format

Inputs (Phase 3+):
  cross_domain_output (dict), calendar (dict), weather (dict),
  spiritual (dict), local_items (list), seam_data (dict), raw_sources (dict)

Inputs (Phase 1):
  domain_analysis (dict), calendar (dict), weather (dict),
  spiritual (dict), local_items (list), seam_data (dict), raw_sources (dict)

Outputs: html (str), template_data (dict), digest_json (dict)

Security Layer 4 (Jinja2 autoescape) is enforced here: deep dive body HTML is
sanitized by morning_digest.validate and then wrapped in Markup() before template rendering.
"""

import logging
import re
from markupsafe import Markup

from morning_digest.contracts import (
    normalize_cross_domain_output_artifact,
    normalize_domain_analysis,
    normalize_seam_annotations_artifact,
)
from templates.email_template import render_email
from utils.time import format_display_date, format_display_time, now_local, tz_abbrev
from utils.urls import registered_domain

log = logging.getLogger(__name__)

# Tag → label mapping for display
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
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}
_HEDGED_SEAM_RE = re.compile(
    r"^\s*(some analysts argue|critics say|observers (?:say|believe)|"
    r"some experts (?:say|argue)|there are concerns)\b",
    re.IGNORECASE,
)


def _item_to_glance(item: dict) -> dict:
    """Convert a domain or cross-domain item to at_a_glance format.

    Preserves facts, analysis, and cross_domain_note as separate fields so the
    template can render them with distinct voice labels (SOURCES / ANALYSIS / THREAD).
    Also builds a flat `context` string as a fallback for degraded rendering.
    """
    tag = item.get("tag", "")
    facts = item.get("facts", "")
    analysis = item.get("analysis", "")
    cross_note = item.get("cross_domain_note", "")
    parts = [p for p in [facts, analysis] if p]
    if cross_note:
        parts.append(f"({cross_note})")
    return {
        "item_id": item.get("item_id", ""),
        "tag": tag,
        "tag_label": item.get("tag_label") or _TAG_LABELS.get(tag, tag.capitalize()),
        "headline": item.get("headline", ""),
        "facts": facts,
        "analysis": analysis,
        "cross_domain_note": cross_note,
        "context": " ".join(parts),
        "links": item.get("links", []),
        "source_depth": item.get("source_depth", ""),
        "connection_hooks": item.get("connection_hooks", []),
    }


def _truncate_one_line(text: str, limit: int = 220) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    truncated = text[:limit].rstrip()
    for marker in (". ", "? ", "! "):
        idx = truncated.rfind(marker)
        if idx >= 80:
            return truncated[: idx + 1].rstrip()
    return truncated.rstrip(" ,;:") + "..."


def _outlet_from_links(links: list[dict]) -> str:
    """Return the most common registered domain from a list of links."""
    from collections import Counter

    domains = [registered_domain(lnk.get("url", "")) for lnk in links if lnk.get("url")]
    if not domains:
        return ""
    return Counter(domains).most_common(1)[0][0]


def _enforce_source_caps(
    items: list[dict],
    max_per_outlet: int,
    section_name: str,
) -> list[dict]:
    """Drop items that exceed the per-outlet cap, preserving priority order."""
    counts: dict[str, int] = {}
    kept: list[dict] = []
    dropped: list[dict] = []
    for item in items:
        outlet = _outlet_from_links(item.get("links", []) or item.get("further_reading", []))
        if not outlet:
            kept.append(item)
            continue
        if counts.get(outlet, 0) >= max_per_outlet:
            dropped.append(item)
            continue
        counts[outlet] = counts.get(outlet, 0) + 1
        kept.append(item)
    if dropped:
        log.info(
            f"assemble: dropped {len(dropped)} {section_name} item(s) for "
            f"per-outlet cap (max {max_per_outlet} per outlet)"
        )
    return kept


def _select_inline_seam_annotations(
    at_a_glance: list[dict], seam_annotations: dict
) -> list[dict]:
    """Attach at most one renderable seam annotation to each at-a-glance item."""
    candidates: dict[str, dict] = {}
    for annotation in seam_annotations.get("per_item", []) or []:
        if not isinstance(annotation, dict):
            continue
        item_id = str(annotation.get("item_id", "")).strip()
        one_line = str(annotation.get("one_line", "")).strip()
        if not item_id or not one_line:
            continue
        if _HEDGED_SEAM_RE.match(one_line):
            log.warning(
                f"assemble: seam annotation for {item_id!r} starts with hedged voice"
            )
        existing = candidates.get(item_id)
        rank = _CONFIDENCE_RANK.get(str(annotation.get("confidence", "")).lower(), 0)
        existing_rank = _CONFIDENCE_RANK.get(
            str((existing or {}).get("confidence", "")).lower(), -1
        )
        if existing is None or rank > existing_rank:
            candidates[item_id] = annotation

    rendered = []
    for item in at_a_glance:
        item_copy = dict(item)
        annotation = candidates.get(str(item.get("item_id", "")).strip())
        if annotation:
            item_copy["seam_annotation"] = {
                "one_line": _truncate_one_line(annotation.get("one_line", "")),
                "seam_type": annotation.get("seam_type", ""),
                "confidence": annotation.get("confidence", ""),
            }
        rendered.append(item_copy)
    return rendered


def _domain_item_to_deep_dive(item: dict) -> dict:
    """Convert a deep_dive_candidate domain item to deep_dives format."""
    facts = item.get("facts", "")
    analysis = item.get("analysis", "")

    body_parts = []
    if facts:
        body_parts.append(f"<p>{facts}</p>")
    if analysis:
        body_parts.append(f"<p>{analysis}</p>")

    return {
        "headline": item.get("headline", ""),
        "tag": item.get("tag", ""),  # preserved for anomaly detection
        "body": "\n".join(body_parts),
        "why_it_matters": item.get(
            "deep_dive_rationale", ""
        ),  # rendered in callout box
        "further_reading": item.get("links", []),
        "source_depth": item.get("source_depth", ""),
    }


def _build_from_domain_analysis(context: dict, config: dict) -> tuple[list, list, str]:
    """Build at_a_glance, deep_dives, market_context from domain_analysis artifact."""
    domain_analysis = context.get("domain_analysis", {})

    all_items: list[dict] = []
    deep_dive_candidates: list[dict] = []
    market_context = ""

    for domain_key, domain_result in domain_analysis.items():
        if domain_key == "econ" and domain_result.get("market_context"):
            market_context = domain_result["market_context"]
        for item in domain_result.get("items", []):
            if item.get("deep_dive_candidate"):
                deep_dive_candidates.append(item)
            else:
                all_items.append(item)

    # Sort all items: widely-reported first, then corroborated, then single-source
    _depth_order = {"widely-reported": 0, "corroborated": 1, "single-source": 2, "": 3}
    all_items.sort(key=lambda i: _depth_order.get(i.get("source_depth", ""), 3))

    # Enforce at_a_glance count limits from config (Phase 1 fallback only;
    # Phase 3 cross_domain enforces caps via its LLM prompt).
    digest_cfg = config.get("digest", {}).get("at_a_glance", {})
    max_items = digest_cfg.get("max_items", 7)
    normal_items = digest_cfg.get("normal_items", 5)
    cap = min(max_items, max(normal_items, len(all_items)))

    at_a_glance = [_item_to_glance(i) for i in all_items[:cap]]

    # Select up to 3 deep dives from candidates
    max_dives = config.get("digest", {}).get("deep_dives", {}).get("count", 2)
    selected_dives = deep_dive_candidates[:max_dives]
    deep_dives = [_domain_item_to_deep_dive(i) for i in selected_dives]

    return at_a_glance, deep_dives, market_context


def _extract_peripheral_data(context: dict, raw_sources: dict) -> dict:
    """Extract spiritual, weather, calendar, and local data from context with raw_sources fallback."""
    spiritual = context.get("spiritual")
    if not spiritual:
        cfm = raw_sources.get("come_follow_me", {})
        spiritual = (
            {**cfm, "reflection": cfm.get("scripture_text", "")} if cfm else None
        )
    calendar = context.get("calendar", {})
    return {
        "spiritual": spiritual,
        "weather": context.get("weather") or raw_sources.get("weather", {}),
        "weather_html": context.get("weather_html", ""),
        "week_ahead": calendar.get("events", []),
        "local_items": context.get("local_items") or raw_sources.get("local_news", []),
        "regional_items": context.get("regional_items") or [],
    }


def _visible_stage_failures(context: dict, config: dict, dry_run: bool) -> list[dict]:
    """Return stage failures that should be visible in rendered email."""
    failures = context.get("run_meta", {}).get("stage_failures", []) or []
    mode = config.get("digest", {}).get("failure_visibility", "artifacts_only")
    if mode == "always":
        return failures
    if mode == "dry_run" and dry_run:
        return failures
    return []


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Assemble template data, render HTML, and return html + template_data artifacts."""
    seam_data = context.get("seam_data", {})
    raw_sources = context.get("raw_sources", {})
    dry_run = kwargs.get("dry_run", False)
    assemble_contract_issues: list[dict] = []

    domain_analysis = {}
    if "domain_analysis" in context:
        domain_analysis, domain_issues = normalize_domain_analysis(
            context.get("domain_analysis", {})
        )
        assemble_contract_issues.extend(
            {"artifact": "domain_analysis", **issue} for issue in domain_issues
        )

    seam_annotations, seam_annotation_issues = normalize_seam_annotations_artifact(
        context.get("seam_annotations", {}), domain_analysis
    )
    assemble_contract_issues.extend(
        {"artifact": "seam_annotations", **issue}
        for issue in seam_annotation_issues
    )

    cross_domain_output = {}
    if "cross_domain_output" in context:
        cross_domain_output, cross_domain_issues = (
            normalize_cross_domain_output_artifact(context.get("cross_domain_output"))
        )
        assemble_contract_issues.extend(
            {"artifact": "cross_domain_output", **issue}
            for issue in cross_domain_issues
        )

    today = now_local()

    # --- Select pipeline mode ---
    use_cross_domain_output = bool(
        cross_domain_output.get("at_a_glance")
        or cross_domain_output.get("deep_dives")
        or cross_domain_output.get("worth_reading")
        or cross_domain_output.get("market_context")
        or cross_domain_output.get("cross_domain_connections")
    )
    if use_cross_domain_output:
        log.info("assemble: using cross_domain_output (Phase 3 mode)")
        xd = cross_domain_output
        at_a_glance = [_item_to_glance(i) for i in xd.get("at_a_glance", [])]
        deep_dives_raw = xd.get("deep_dives", [])
        market_context = xd.get("market_context", "")
        worth_reading = xd.get("worth_reading", [])

    elif domain_analysis:
        log.info("assemble: using domain_analysis artifacts (Phase 1 mode)")
        at_a_glance, deep_dives_raw, market_context = _build_from_domain_analysis(
            {**context, "domain_analysis": domain_analysis}, config
        )
        worth_reading = []

    else:
        log.error(
            "assemble: no pipeline output found in context — producing empty digest"
        )
        at_a_glance = []
        deep_dives_raw = []
        market_context = ""
        worth_reading = []

    # Enforce per-outlet source caps to prevent false corroboration
    digest_cfg = config.get("digest", {})
    glance_cfg = digest_cfg.get("at_a_glance", {})
    dive_cfg = digest_cfg.get("deep_dives", {})
    at_a_glance = _enforce_source_caps(
        at_a_glance,
        max_per_outlet=glance_cfg.get("max_per_outlet", 2),
        section_name="at-a-glance",
    )
    deep_dives_raw = _enforce_source_caps(
        deep_dives_raw,
        max_per_outlet=dive_cfg.get("max_per_outlet", 1),
        section_name="deep-dive",
    )

    peripheral = _extract_peripheral_data(context, raw_sources)
    spiritual = peripheral["spiritual"]
    weather = peripheral["weather"]
    weather_html = peripheral["weather_html"]
    week_ahead = peripheral["week_ahead"]
    local_items = peripheral["local_items"]
    regional_items = peripheral["regional_items"]
    markets = raw_sources.get("markets", [])

    # Build source name lists for footer
    rss_names = [f["name"] for f in config.get("rss", {}).get("feeds", [])]
    local_names = [s["name"] for s in config.get("local_news", {}).get("sources", [])]
    yt_names = [
        c["name"] for c in config.get("youtube", {}).get("analysis_channels", [])
    ]
    rss_source_names = ", ".join(rss_names + local_names) or "RSS feeds"
    yt_source_names = ", ".join(yt_names) if yt_names else ""

    # Security Layer 4: mark sanitized deep dive body HTML as safe for Jinja2
    deep_dives = []
    for dive in deep_dives_raw:
        dive_copy = dict(dive)
        if dive_copy.get("body"):
            dive_copy["body"] = Markup(dive_copy["body"])
        deep_dives.append(dive_copy)

    # Mark weather_html as safe (SVG display module generates trusted HTML)
    if weather_html:
        weather_html = Markup(weather_html)

    # Detect analysis failures: we had source data but no items came through
    domain_failures = context.get("domain_analysis_failures", [])
    raw_rss_count = len(raw_sources.get("rss", []))
    analysis_unavailable = bool(domain_failures) and not at_a_glance and raw_rss_count > 0
    coverage_gap_diagnostics = context.get("coverage_gaps", {}) if dry_run else {}
    stage_failures = _visible_stage_failures(context, config, dry_run)
    at_a_glance = _select_inline_seam_annotations(at_a_glance, seam_annotations)

    template_data = {
        "date_display": format_display_date(today),
        "generated_at": f"{format_display_time(today)} {tz_abbrev(today)}",
        "rss_source_names": rss_source_names,
        "yt_source_names": yt_source_names,
        "spiritual": spiritual,
        "weather": weather,
        "weather_html": weather_html,
        "markets": markets,
        "at_a_glance": at_a_glance,
        "analysis_unavailable": analysis_unavailable,
        "seam_annotations": seam_annotations,
        "contested_narratives": seam_data.get("contested_narratives", []),
        "coverage_gaps": seam_data.get("coverage_gaps", []),
        "key_assumptions": seam_data.get("key_assumptions", []),
        "coverage_gap_diagnostics": coverage_gap_diagnostics,
        "local_items": local_items,
        "regional_items": regional_items,
        "market_context": market_context,
        "week_ahead": week_ahead,
        "worth_reading": worth_reading,
        "deep_dives": deep_dives,
        "stage_failures": stage_failures,
    }

    html = render_email(template_data)

    # digest_json mirrors template_data but with:
    # - deep dive body as plain string (not Markup) for artifact storage
    # - cross_domain metadata preserved for briefing_packet and future use
    digest_json = dict(template_data)
    digest_json["deep_dives"] = deep_dives_raw
    digest_json["cross_domain_connections"] = cross_domain_output.get(
        "cross_domain_connections", []
    )
    digest_json["assemble_contract_issues"] = assemble_contract_issues

    log.info(
        f"assemble: rendered digest — "
        f"{len(at_a_glance)} at-a-glance, "
        f"{len(deep_dives)} deep dives, "
        f"{len(seam_data.get('contested_narratives', []))} seams"
    )

    return {
        "html": html,
        "template_data": template_data,
        "digest_json": digest_json,
        "assemble_contract_issues": assemble_contract_issues,
    }
