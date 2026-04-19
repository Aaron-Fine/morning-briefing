"""Fetch and aggregate RSS feeds — direct or via FreshRSS API."""

import logging
import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Optional
import feedparser
import requests
from dateutil import parser as dateparser

from sources._http import http_get_bytes

log = logging.getLogger(__name__)

_MAX_PARALLEL_FEED_FETCHES = 6


def fetch_rss(config: dict) -> list[dict]:
    """Return recent RSS items from configured feeds.
    
    Returns list of dicts: {source, title, url, published, summary}
    """
    rss_config = config.get("rss", {})
    provider = rss_config.get("provider", "direct")

    if provider == "freshrss" and rss_config.get("freshrss_url"):
        return _fetch_from_freshrss(rss_config)
    else:
        return _fetch_direct(rss_config)


class _FeedParseTimeout(Exception):
    pass


def _parse_feed_with_timeout(content: bytes, feed_name: str, timeout_secs: int = 10):
    """Parse feed content with a SIGALRM timeout guard.

    feedparser.parse() has no built-in timeout and can hang on deeply nested
    or malformed XML content.
    """
    def _handler(signum, frame):
        raise _FeedParseTimeout(f"feedparser.parse() timed out for {feed_name}")

    prev_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout_secs)
    try:
        return feedparser.parse(content)
    except _FeedParseTimeout:
        log.warning(f"Feed parse timed out for {feed_name} (>{timeout_secs}s)")
        return feedparser.FeedParserDict(entries=[])
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev_handler)


def _fetch_direct(rss_config: dict) -> list[dict]:
    """Fetch from individual RSS feed URLs."""
    feeds = rss_config.get("feeds", [])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    all_items = []
    consecutive_failures = 0

    for start in range(0, len(feeds), _MAX_PARALLEL_FEED_FETCHES):
        batch = feeds[start:start + _MAX_PARALLEL_FEED_FETCHES]
        batch_contents = _fetch_feed_batch(batch)

        for feed_conf, feed_content in zip(batch, batch_contents):
            if consecutive_failures >= 5:
                remaining = len(feeds) - feeds.index(feed_conf)
                log.warning(
                    f"RSS: {consecutive_failures} consecutive fetch failures — "
                    f"network likely down, skipping remaining {remaining} feeds"
                )
                break

            if feed_content is None:
                consecutive_failures += 1
                continue

            consecutive_failures = 0
            try:
                parsed = _parse_feed_with_timeout(feed_content, feed_conf["name"])
                cap = feed_conf.get("cap", 15)
                tag = feed_conf.get("tag", "")
                for entry in parsed.entries[:cap]:
                    published = _parse_feed_date(entry)
                    if published and published < cutoff:
                        continue

                    item = {
                        "source": feed_conf["name"],
                        "title": entry.get("title", "").strip(),
                        "url": entry.get("link", ""),
                        "published": published.isoformat() if published else "",
                        "summary": _clean_summary(entry.get("summary", "")),
                    }
                    if tag:
                        item["tag"] = tag
                    category = feed_conf.get("category", "")
                    if category:
                        item["category"] = category
                    all_items.append(item)
            except Exception as e:
                log.warning(f"RSS parse failed for {feed_conf['name']}: {e}")
        else:
            continue
        break

    if all_items:
        log.info(f"RSS: fetched {len(all_items)} items from {len(feeds)} feeds")
    else:
        log.warning("RSS: no items fetched from any feed")
    all_items.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_items


def _fetch_feed_batch(feeds: list[dict]) -> list[bytes | None]:
    """Fetch one batch of feed bytes in parallel, preserving input order."""
    max_workers = min(_MAX_PARALLEL_FEED_FETCHES, len(feeds) or 1)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(_fetch_feed_content, feeds))


def _fetch_feed_content(feed_conf: dict) -> bytes | None:
    """Fetch raw feed bytes for one configured feed."""
    return http_get_bytes(
        feed_conf["url"], timeout=15, label=f"RSS {feed_conf['name']}"
    )


def _fetch_from_freshrss(rss_config: dict) -> list[dict]:
    """Fetch unread items from FreshRSS Google Reader-compatible API."""
    base = rss_config["freshrss_url"].rstrip("/")
    user = rss_config.get("freshrss_user", "")
    password = rss_config.get("freshrss_password", "")

    try:
        # Authenticate
        auth_resp = requests.post(
            f"{base}/accounts/ClientLogin",
            data={"Email": user, "Passwd": password},
            timeout=10,
        )
        auth_resp.raise_for_status()
        auth_token = None
        for line in auth_resp.text.strip().split("\n"):
            if line.startswith("Auth="):
                auth_token = line[5:]
                break

        if not auth_token:
            log.error("FreshRSS auth failed — no token")
            return []

        headers = {"Authorization": f"GoogleLogin auth={auth_token}"}

        # Fetch unread items
        items_resp = requests.get(
            f"{base}/reader/api/0/stream/contents/reading-list",
            params={"n": 100, "xt": "user/-/state/com.google/read"},
            headers=headers,
            timeout=15,
        )
        items_resp.raise_for_status()
        data = items_resp.json()

        results = []
        for item in data.get("items", []):
            results.append({
                "source": item.get("origin", {}).get("title", "RSS"),
                "title": item.get("title", "").strip(),
                "url": next(
                    (a["href"] for a in item.get("alternate", []) if "href" in a),
                    "",
                ),
                "published": datetime.fromtimestamp(
                    item.get("published", 0), tz=timezone.utc
                ).isoformat(),
                "summary": _clean_summary(
                    item.get("summary", {}).get("content", "")
                ),
            })

        return results

    except Exception as e:
        log.error(f"FreshRSS fetch failed: {e}")
        return _fetch_direct(rss_config)  # fallback to direct


def _parse_feed_date(entry) -> Optional[datetime]:
    """Extract and parse date from a feed entry. Always returns UTC-aware."""
    for field in ("published_parsed", "updated_parsed"):
        val = entry.get(field)
        if val:
            from time import mktime
            return datetime.fromtimestamp(mktime(val), tz=timezone.utc)

    for field in ("published", "updated"):
        val = entry.get(field)
        if val:
            try:
                dt = dateparser.parse(val)
            except Exception:
                continue
            if dt is None:
                continue
            # dateparser may return a naive datetime for strings without an
            # explicit offset; assume UTC so downstream comparisons don't raise.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt

    return None


def _clean_summary(raw: str) -> str:
    """Strip HTML and truncate summary."""
    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self._parts = []
        def handle_data(self, d):
            self._parts.append(d)
        def get_text(self):
            return " ".join(self._parts)

    stripper = _Stripper()
    stripper.feed(raw)
    text = " ".join(stripper.get_text().split())  # collapse whitespace
    if len(text) > 400:
        text = text[:397] + "..."
    return text
