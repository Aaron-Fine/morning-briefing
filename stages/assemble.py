"""Stage: assemble — Merge all stage outputs and render the HTML digest.

Supports three pipeline configurations:
  Phase 3+: cross_domain_output present → use editor-in-chief output
  Phase 1:  domain_analysis present → merge domain artifacts into template format
  Phase 0:  synthesis_output present → use directly (backward compat)

Inputs (Phase 3+):
  cross_domain_output (dict), calendar (dict), weather (dict),
  spiritual (dict), local_items (list), seam_data (dict), raw_sources (dict)

Inputs (Phase 1):
  domain_analysis (dict), calendar (dict), weather (dict),
  spiritual (dict), local_items (list), seam_data (dict), raw_sources (dict)

Inputs (Phase 0 fallback):
  synthesis_output (dict), seam_data (dict), raw_sources (dict)

Outputs: html (str), template_data (dict), digest_json (dict)

Security Layer 4 (Jinja2 autoescape) is enforced here: deep dive body HTML is
sanitized by morning_digest.validate and then wrapped in Markup() before template rendering.
"""

import logging
from markupsafe import Markup

from templates.email_template import render_email
from utils.time import format_display_date, format_display_time, now_local, tz_abbrev

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


def _item_to_glance(item: dict) -> dict:
    """Convert a domain or cross-domain item to at_a_glance format.

    Preserves facts, analysis, and cross_domain_note as separate fields so the
    template can render them with distinct voice labels (SOURCES / ANALYSIS / THREAD).
    Also builds a flat `context` string as a fallback for Phase 0 rendering.
    """
    tag = item.get("tag", "")
    facts = item.get("facts", "")
    analysis = item.get("analysis", "")
    cross_note = item.get("cross_domain_note", "")
    parts = [p for p in [facts, analysis] if p]
    if cross_note:
        parts.append(f"({cross_note})")
    return {
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
    }


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Assemble template data, render HTML, and return html + template_data artifacts."""
    seam_data = context.get("seam_data", {})
    raw_sources = context.get("raw_sources", {})
    dry_run = kwargs.get("dry_run", False)

    today = now_local()

    # --- Select pipeline mode ---
    if context.get("cross_domain_output"):
        log.info("assemble: using cross_domain_output (Phase 3 mode)")
        xd = context["cross_domain_output"]
        at_a_glance = [_item_to_glance(i) for i in xd.get("at_a_glance", [])]
        deep_dives_raw = xd.get("deep_dives", [])
        market_context = xd.get("market_context", "")
        worth_reading = xd.get("worth_reading", [])

    elif context.get("domain_analysis"):
        log.info("assemble: using domain_analysis artifacts (Phase 1 mode)")
        at_a_glance, deep_dives_raw, market_context = _build_from_domain_analysis(
            context, config
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

    peripheral = _extract_peripheral_data(context, raw_sources)
    spiritual = peripheral["spiritual"]
    weather = peripheral["weather"]
    weather_html = peripheral["weather_html"]
    week_ahead = peripheral["week_ahead"]
    local_items = peripheral["local_items"]
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
        "contested_narratives": seam_data.get("contested_narratives", []),
        "coverage_gaps": seam_data.get("coverage_gaps", []),
        "key_assumptions": seam_data.get("key_assumptions", []),
        "coverage_gap_diagnostics": coverage_gap_diagnostics,
        "local_items": local_items,
        "market_context": market_context,
        "week_ahead": week_ahead,
        "worth_reading": worth_reading,
        "deep_dives": deep_dives,
    }

    html = render_email(template_data)

    # digest_json mirrors template_data but with:
    # - deep dive body as plain string (not Markup) for artifact storage
    # - cross_domain metadata preserved for briefing_packet and future use
    digest_json = dict(template_data)
    digest_json["deep_dives"] = deep_dives_raw
    xd = context.get("cross_domain_output", {})
    digest_json["cross_domain_connections"] = xd.get("cross_domain_connections", [])

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
    }
