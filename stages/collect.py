"""Stage: collect — Gather raw data from all configured sources.

Inputs:  (none — reads from external sources)
Outputs: raw_sources (dict)
"""

import logging

from sanitize import sanitize_all_sources
from sources.youtube import fetch_analysis_transcripts
from sources.weather import fetch_weather
from sources.markets import fetch_markets
from sources.launches import fetch_upcoming_launches
from sources.rss_feeds import fetch_rss
from sources.come_follow_me import get_current_lesson, get_upcoming_church_events
from sources.holidays import get_upcoming_holidays

log = logging.getLogger(__name__)


def run(inputs: dict, config: dict, model_config: dict | None = None) -> dict:
    """Collect all sources and return raw_sources artifact."""
    log.info("Collecting from sources...")
    data: dict = {}

    # Weather
    log.info("  → Weather")
    data["weather"] = fetch_weather(config)

    # Markets
    if config.get("digest", {}).get("markets", {}).get("enabled", True):
        log.info("  → Markets")
        data["markets"] = fetch_markets(config)

    # Upcoming space launches
    log.info("  → Space launches")
    data["launches"] = fetch_upcoming_launches()

    # Church events + holidays
    data["church_events"] = get_upcoming_church_events()
    data["holidays"] = get_upcoming_holidays(days=10)

    # Come Follow Me
    if config.get("digest", {}).get("spiritual", {}).get("enabled", True):
        log.info("  → Come Follow Me")
        data["come_follow_me"] = get_current_lesson(config)

    # YouTube analysis transcripts
    log.info("  → YouTube analysis channels")
    try:
        data["analysis_transcripts"] = fetch_analysis_transcripts(config)
    except Exception as e:
        log.warning(f"  YouTube analysis failed: {e}")
        data["analysis_transcripts"] = []

    # RSS feeds
    log.info("  → RSS feeds")
    data["rss"] = fetch_rss(config)

    # Local news (separate so downstream stages can distinguish them)
    local_sources = config.get("local_news", {}).get("sources", [])
    if local_sources:
        log.info("  → Local news")
        local_rss_config = {"rss": {"feeds": local_sources, "provider": "direct"}}
        data["local_news"] = fetch_rss(local_rss_config)
    else:
        data["local_news"] = []

    data["source_counts"] = {
        "analysis_transcripts": len(data.get("analysis_transcripts", [])),
        "rss_items": len(data.get("rss", [])),
        "local_news_items": len(data.get("local_news", [])),
    }

    log.info(
        f"  Collected: {data['source_counts']['rss_items']} RSS items, "
        f"{data['source_counts']['local_news_items']} local news items, "
        f"{data['source_counts']['analysis_transcripts']} analysis transcripts"
    )

    # Security Layer 1: sanitize all source content before it touches any prompt
    log.info("  → Sanitizing source content (Layer 1)")
    data = sanitize_all_sources(data)

    return {"raw_sources": data}
