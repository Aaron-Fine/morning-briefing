"""Fetch and aggregate RSS feeds — direct or via FreshRSS API."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import feedparser
import requests

log = logging.getLogger(__name__)


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


def _fetch_direct(rss_config: dict) -> list[dict]:
    """Fetch from individual RSS feed URLs."""
    feeds = rss_config.get("feeds", [])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    all_items = []

    for feed_conf in feeds:
        try:
            parsed = feedparser.parse(
                feed_conf["url"],
                request_headers={"User-Agent": "MorningDigest/1.0"},
            )
            for entry in parsed.entries[:15]:  # cap per feed
                published = _parse_feed_date(entry)
                if published and published < cutoff:
                    continue

                all_items.append({
                    "source": feed_conf["name"],
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link", ""),
                    "published": published.isoformat() if published else "",
                    "summary": _clean_summary(entry.get("summary", "")),
                })
        except Exception as e:
            log.warning(f"RSS fetch failed for {feed_conf['name']}: {e}")

    all_items.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_items


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
    """Extract and parse date from a feed entry."""
    from dateutil import parser as dateparser

    for field in ("published_parsed", "updated_parsed"):
        val = entry.get(field)
        if val:
            from time import mktime
            return datetime.fromtimestamp(mktime(val), tz=timezone.utc)

    for field in ("published", "updated"):
        val = entry.get(field)
        if val:
            try:
                return dateparser.parse(val)
            except Exception:
                continue

    return None


def _clean_summary(raw: str) -> str:
    """Strip HTML and truncate summary."""
    from bs4 import BeautifulSoup

    text = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)
    if len(text) > 400:
        text = text[:397] + "..."
    return text
