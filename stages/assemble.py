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
sanitized by validate.py and then wrapped in Markup() before template rendering.
"""

import logging
from datetime import datetime
from markupsafe import Markup

from templates.email_template import render_email

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


# Keep aliases so any future code that references the old names doesn't break silently.
_cross_domain_item_to_glance = _item_to_glance
_domain_item_to_glance = _item_to_glance


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

    # Enforce at_a_glance count limits from config
    digest_cfg = config.get("digest", {}).get("at_a_glance", {})
    max_items = digest_cfg.get("max_items", 14)
    normal_items = digest_cfg.get("normal_items", 10)
    cap = min(max_items, max(normal_items, len(all_items)))

    at_a_glance = [_domain_item_to_glance(i) for i in all_items[:cap]]

    # Select up to 3 deep dives from candidates
    max_dives = config.get("digest", {}).get("deep_dives", {}).get("count", 2)
    selected_dives = deep_dive_candidates[:max_dives]
    deep_dives = [_domain_item_to_deep_dive(i) for i in selected_dives]

    return at_a_glance, deep_dives, market_context


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Assemble template data, render HTML, and return html + template_data artifacts."""
    seam_data = context.get("seam_data", {})
    raw_sources = context.get("raw_sources", {})

    today = datetime.now()

    # --- Select pipeline mode ---
    if context.get("cross_domain_output"):
        # Phase 3+: use editor-in-chief cross-domain synthesis output
        log.info("assemble: using cross_domain_output (Phase 3 mode)")
        xd = context["cross_domain_output"]
        at_a_glance = [
            _cross_domain_item_to_glance(i) for i in xd.get("at_a_glance", [])
        ]
        deep_dives_raw = xd.get("deep_dives", [])
        market_context = xd.get("market_context", "")
        weekend_reads = xd.get("weekend_reads", [])

        spiritual = context.get("spiritual")
        if not spiritual:
            cfm = raw_sources.get("come_follow_me", {})
            spiritual = (
                {**cfm, "reflection": cfm.get("scripture_text", "")} if cfm else None
            )
        weather = context.get("weather") or raw_sources.get("weather", {})
        weather_html = context.get("weather_html", "")
        calendar = context.get("calendar", {})
        week_ahead = calendar.get("events", [])
        local_items = context.get("local_items") or raw_sources.get("local_news", [])

    elif context.get("domain_analysis"):
        # Phase 1: build from domain artifacts (no cross-domain synthesis)
        log.info("assemble: using domain_analysis artifacts (Phase 1 mode)")
        at_a_glance, deep_dives_raw, market_context = _build_from_domain_analysis(
            context, config
        )
        weekend_reads = []

        spiritual = context.get("spiritual")
        if not spiritual:
            cfm = raw_sources.get("come_follow_me", {})
            spiritual = (
                {**cfm, "reflection": cfm.get("scripture_text", "")} if cfm else None
            )
        weather = context.get("weather") or raw_sources.get("weather", {})
        weather_html = context.get("weather_html", "")
        calendar = context.get("calendar", {})
        week_ahead = calendar.get("events", [])
        local_items = context.get("local_items") or raw_sources.get("local_news", [])

    else:
        log.error(
            "assemble: no pipeline output found in context — producing empty digest"
        )
        at_a_glance = []
        deep_dives_raw = []
        market_context = ""
        weekend_reads = []
        week_ahead = []
        local_items = []
        spiritual = None
        weather = raw_sources.get("weather", {})
        weather_html = ""

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

    template_data = {
        "date_display": today.strftime("%A, %B %-d, %Y"),
        "generated_at": (
            today.strftime("%-I:%M %p")
            + " "
            + config.get("location", {})
            .get("timezone", "America/Denver")
            .split("/")[-1]
        ),
        "rss_source_names": rss_source_names,
        "yt_source_names": yt_source_names,
        "spiritual": spiritual,
        "weather": weather,
        "weather_html": weather_html,
        "markets": markets,
        "at_a_glance": at_a_glance,
        "contested_narratives": seam_data.get("contested_narratives", []),
        "coverage_gaps": seam_data.get("coverage_gaps", []),
        "key_assumptions": seam_data.get("key_assumptions", []),
        "local_items": local_items,
        "market_context": market_context,
        "week_ahead": week_ahead,
        "weekend_reads": weekend_reads,
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
