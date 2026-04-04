"""Stage: assemble — Merge all stage outputs and render the HTML digest.

Inputs:  synthesis_output (dict), seam_data (dict), raw_sources (dict)
Outputs: html (str), template_data (dict), digest_json (dict)

Security Layer 4 (Jinja2 autoescape) is enforced here: deep dive body HTML is
sanitized by validate.py and then wrapped in Markup() before template rendering.
"""

import logging
from datetime import datetime
from markupsafe import Markup

from templates.email_template import render_email

log = logging.getLogger(__name__)


def run(inputs: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    """Assemble template data, render HTML, and return html + template_data artifacts."""
    synthesis_output = inputs.get("synthesis_output", {})
    seam_data = inputs.get("seam_data", {})
    raw_sources = inputs.get("raw_sources", {})

    today = datetime.now()
    weather = raw_sources.get("weather", {})
    markets = raw_sources.get("markets", [])
    cfm = raw_sources.get("come_follow_me", {})

    # Spiritual thought
    spiritual = None
    if cfm.get("scripture_text"):
        spiritual = {
            **cfm,
            "reflection": synthesis_output.get("spiritual_reflection", ""),
        }

    # Build source name lists for footer
    rss_names = [f["name"] for f in config.get("rss", {}).get("feeds", [])]
    local_names = [s["name"] for s in config.get("local_news", {}).get("sources", [])]
    yt_names = [c["name"] for c in config.get("youtube", {}).get("analysis_channels", [])]
    all_source_names = rss_names + local_names
    rss_source_names = ", ".join(all_source_names) if all_source_names else "RSS feeds"
    yt_source_names = ", ".join(yt_names) if yt_names else ""

    # Security Layer 4: mark sanitized deep dive body HTML as safe for Jinja2
    # (validate.py already stripped disallowed tags; Markup() tells Jinja2 not to escape it)
    deep_dives = []
    for dive in synthesis_output.get("deep_dives", []):
        dive_copy = dict(dive)
        if dive_copy.get("body"):
            dive_copy["body"] = Markup(dive_copy["body"])
        deep_dives.append(dive_copy)

    template_data = {
        "date_display": today.strftime("%A, %B %-d, %Y"),
        "generated_at": (
            today.strftime("%-I:%M %p") + " "
            + config.get("location", {}).get("timezone", "America/Denver").split("/")[-1]
        ),
        "rss_source_names": rss_source_names,
        "yt_source_names": yt_source_names,
        "spiritual": spiritual,
        "weather": weather,
        "markets": markets,
        "at_a_glance": synthesis_output.get("at_a_glance", []),
        "contested_narratives": seam_data.get("contested_narratives", []),
        "coverage_gaps": seam_data.get("coverage_gaps", []),
        "local_items": synthesis_output.get("local_items", []),
        "market_context": synthesis_output.get("market_context", ""),
        "week_ahead": synthesis_output.get("week_ahead", []),
        "weekend_reads": synthesis_output.get("weekend_reads", []),
        "deep_dives": deep_dives,
    }

    html = render_email(template_data)

    # digest_json mirrors template_data but with body as plain string (for artifact storage)
    digest_json = dict(template_data)
    digest_json["deep_dives"] = synthesis_output.get("deep_dives", [])  # plain string, not Markup

    log.info(
        f"assemble: rendered digest — "
        f"{len(template_data['at_a_glance'])} at-a-glance, "
        f"{len(deep_dives)} deep dives, "
        f"{len(seam_data.get('contested_narratives', []))} seams"
    )

    return {
        "html": html,
        "template_data": template_data,
        "digest_json": digest_json,
    }
