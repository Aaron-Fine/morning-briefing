"""Stage: collect — Gather raw data from all configured sources.

Inputs:  (none — reads from external sources)
Outputs: raw_sources (dict)
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from sanitize import sanitize_all_sources
from sources.youtube import fetch_analysis_transcripts
from sources.weather import fetch_weather
from sources.markets import fetch_markets
from sources.launches import fetch_upcoming_launches
from sources.rss_feeds import fetch_rss
from sources.come_follow_me import get_current_lesson, get_upcoming_church_events
from sources.holidays import get_upcoming_holidays
from sources.economic_calendar import fetch_economic_calendar

log = logging.getLogger(__name__)

_MAX_PARALLEL_FETCHES = 6


def _fetch_weather(config):
    log.info("  → Weather")
    return "weather", fetch_weather(config)


def _fetch_markets(config):
    log.info("  → Markets")
    return "markets", fetch_markets(config)


def _fetch_launches(_config):
    log.info("  → Space launches")
    return "launches", fetch_upcoming_launches()


def _fetch_calendar(config):
    log.info("  → Calendar events")
    church_events = get_upcoming_church_events()
    holidays = get_upcoming_holidays(days=10)
    economic_calendar = fetch_economic_calendar(config)
    return "calendar", {
        "church_events": church_events,
        "holidays": holidays,
        "economic_calendar": economic_calendar,
    }


def _fetch_come_follow_me(config):
    log.info("  → Come Follow Me")
    return "come_follow_me", get_current_lesson(config)


def _fetch_youtube(config):
    log.info("  → YouTube analysis channels")
    try:
        return "analysis_transcripts", fetch_analysis_transcripts(config)
    except Exception as e:
        log.warning(f"  YouTube analysis failed: {e}")
        return "analysis_transcripts", []


def _fetch_rss(config):
    log.info("  → RSS feeds")
    return "rss", fetch_rss(config)


def _fetch_local_news(config):
    local_sources = config.get("local_news", {}).get("sources", [])
    if local_sources:
        log.info("  → Local news")
        local_rss_config = {"rss": {"feeds": local_sources, "provider": "direct"}}
        return "local_news", fetch_rss(local_rss_config)
    return "local_news", []


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    """Collect all sources and return raw_sources artifact."""
    log.info("Collecting from sources (parallel)...")
    data: dict = {}

    tasks = [
        (_fetch_weather, config),
        (_fetch_launches, config),
        (_fetch_calendar, config),
        (_fetch_youtube, config),
        (_fetch_rss, config),
        (_fetch_local_news, config),
    ]

    if config.get("digest", {}).get("markets", {}).get("enabled", True):
        tasks.append((_fetch_markets, config))

    if config.get("digest", {}).get("spiritual", {}).get("enabled", True):
        tasks.append((_fetch_come_follow_me, config))

    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_FETCHES) as pool:
        futures = {pool.submit(fn, cfg): fn.__name__ for fn, cfg in tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                key, result = future.result()
                if key == "calendar":
                    data.update(result)
                else:
                    data[key] = result
            except Exception as e:
                log.error(f"  collect[{name}]: fetch failed: {e}")

    # Ensure keys exist even if tasks were skipped or failed
    data.setdefault("weather", {})
    data.setdefault("markets", [])
    data.setdefault("launches", [])
    data.setdefault("church_events", [])
    data.setdefault("holidays", [])
    data.setdefault("economic_calendar", [])
    data.setdefault("come_follow_me", {})
    data.setdefault("analysis_transcripts", [])
    data.setdefault("rss", [])
    data.setdefault("local_news", [])

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
