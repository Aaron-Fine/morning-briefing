"""Stage: collect — Gather raw data from all configured sources.

Inputs:  (none — reads from external sources)
Outputs: raw_sources (dict)
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from morning_digest.sanitize import sanitize_all_sources
from sources.youtube import fetch_analysis_transcripts
from sources.weather import fetch_weather
from sources.markets import fetch_markets
from sources.launches import fetch_upcoming_launches
from sources.rss_feeds import fetch_rss_with_diagnostics
from sources.hackernews import fetch_hackernews
from sources.github_trending import fetch_github_trending
from sources.astronomy import fetch_astronomy
from sources.history import fetch_on_this_day
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
    items, diagnostics = fetch_rss_with_diagnostics(config)
    return "rss", items, {"rss_feeds": diagnostics}


def _fetch_hackernews(config):
    log.info("  → Hacker News")
    return "hackernews", fetch_hackernews(config)


def _fetch_github_trending(config):
    log.info("  → GitHub trending")
    return "github_trending", fetch_github_trending(config)


def _fetch_astronomy(config):
    log.info("  → Astronomy")
    return "astronomy", fetch_astronomy(config)


def _fetch_on_this_day(config):
    log.info("  → On this day")
    return "on_this_day", fetch_on_this_day(config)


def _fetch_local_news(config):
    local_sources = config.get("local_news", {}).get("sources", [])
    if local_sources:
        log.info("  → Local news")
        local_rss_config = {"rss": {"feeds": local_sources, "provider": "direct"}}
        items, diagnostics = fetch_rss_with_diagnostics(local_rss_config)
        return "local_news", items, {"local_news_feeds": diagnostics}
    return "local_news", [], {"local_news_feeds": []}


def _item_count(value) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        if "events" in value and isinstance(value["events"], list):
            return len(value["events"])
        if "selected" in value and isinstance(value["selected"], list):
            return len(value["selected"])
        return None
    return None


def _run_collect_task(fn, cfg):
    started = time.monotonic()
    key = ""
    try:
        result = fn(cfg)
        extra = {}
        if len(result) == 3:
            key, value, extra = result
        else:
            key, value = result
        elapsed = time.monotonic() - started
        diagnostic = {
            "source": key,
            "status": "ok",
            "item_count": _item_count(value),
            "elapsed_seconds": round(elapsed, 2),
            "error": "",
        }
        return key, value, diagnostic, extra
    except Exception as exc:
        elapsed = time.monotonic() - started
        return (
            key or fn.__name__.removeprefix("_fetch_"),
            None,
            {
                "source": key or fn.__name__.removeprefix("_fetch_"),
                "status": "error",
                "item_count": None,
                "elapsed_seconds": round(elapsed, 2),
                "error": str(exc),
            },
            {},
        )


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    """Collect all sources and return raw_sources artifact."""
    log.info("Collecting from sources (parallel)...")
    data: dict = {}
    diagnostics: dict = {"sources": [], "rss_feeds": [], "local_news_feeds": []}

    # RSS parsing and YouTube transcript collection use SIGALRM timeout guards.
    # Python only permits signal handlers in the main thread, so keep those
    # source orchestrators out of this stage's worker pool.
    main_thread_tasks = [
        (_fetch_youtube, config),
        (_fetch_rss, config),
        (_fetch_local_news, config),
    ]

    tasks = [
        (_fetch_weather, config),
        (_fetch_launches, config),
        (_fetch_calendar, config),
        (_fetch_hackernews, config),
        (_fetch_github_trending, config),
        (_fetch_astronomy, config),
        (_fetch_on_this_day, config),
    ]

    if config.get("digest", {}).get("markets", {}).get("enabled", True):
        tasks.append((_fetch_markets, config))

    if config.get("digest", {}).get("spiritual", {}).get("enabled", True):
        tasks.append((_fetch_come_follow_me, config))

    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_FETCHES) as pool:
        futures = {pool.submit(_run_collect_task, fn, cfg): fn.__name__ for fn, cfg in tasks}
        for future in as_completed(futures):
            name = futures[future]
            key, result, diagnostic, extra = future.result()
            diagnostics["sources"].append(diagnostic)
            diagnostics["rss_feeds"].extend(extra.get("rss_feeds", []))
            diagnostics["local_news_feeds"].extend(extra.get("local_news_feeds", []))
            if diagnostic["status"] == "error":
                log.error(f"  collect[{name}]: fetch failed: {diagnostic['error']}")
                continue
            if key == "calendar":
                data.update(result)
            else:
                data[key] = result

    for fn, cfg in main_thread_tasks:
        key, result, diagnostic, extra = _run_collect_task(fn, cfg)
        diagnostics["sources"].append(diagnostic)
        diagnostics["rss_feeds"].extend(extra.get("rss_feeds", []))
        diagnostics["local_news_feeds"].extend(extra.get("local_news_feeds", []))
        if diagnostic["status"] == "error":
            log.error(f"  collect[{fn.__name__}]: fetch failed: {diagnostic['error']}")
            continue
        data[key] = result

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
    data.setdefault("hackernews", [])
    data.setdefault("github_trending", [])
    data.setdefault("astronomy", {})
    data.setdefault("on_this_day", {})
    data.setdefault("local_news", [])

    source_counts = {
        "analysis_transcripts": len(data.get("analysis_transcripts", [])),
        "rss_items": len(data.get("rss", [])),
        "local_news_items": len(data.get("local_news", [])),
        "hackernews_items": len(data.get("hackernews", [])),
        "github_trending_items": len(data.get("github_trending", [])),
        "astronomy_events": len(data.get("astronomy", {}).get("events", [])),
        "history_items": len(data.get("on_this_day", {}).get("selected", [])),
    }
    data["source_counts"] = source_counts

    log.info(
        f"  Collected: {source_counts['rss_items']} RSS items, "
        f"{source_counts['local_news_items']} local news items, "
        f"{source_counts['analysis_transcripts']} analysis transcripts"
    )

    # Security Layer 1: sanitize all source content before it touches any prompt
    log.info("  → Sanitizing source content (Layer 1)")
    data = sanitize_all_sources(data)
    data.setdefault("source_counts", source_counts)

    diagnostics["source_counts"] = source_counts
    return {"raw_sources": data, "collect_diagnostics": diagnostics}
