"""Fetch top stories from Hacker News (no API key required)."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

log = logging.getLogger(__name__)

HN_API = "https://hacker-news.firebaseio.com/v0"


def fetch_hackernews(config: dict) -> list[dict]:
    """Return top HN stories with title, url, score, and comment count.

    Returns list of dicts: {title, url, score, comments, hn_url}
    """
    hn_config = config.get("hackernews", {})
    count = hn_config.get("top_stories", 15)

    try:
        resp = requests.get(f"{HN_API}/topstories.json", timeout=10)
        resp.raise_for_status()
        story_ids = resp.json()[:count]
    except Exception as e:
        log.warning(f"Failed to fetch HN top stories: {e}")
        return []

    stories = []

    def _fetch_item(sid):
        try:
            r = requests.get(f"{HN_API}/item/{sid}.json", timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_item, sid): sid for sid in story_ids}
        for future in as_completed(futures):
            item = future.result()
            if item and item.get("type") == "story" and item.get("title"):
                stories.append({
                    "title": item["title"],
                    "url": item.get("url", ""),
                    "score": item.get("score", 0),
                    "comments": item.get("descendants", 0),
                    "hn_url": f"https://news.ycombinator.com/item?id={item['id']}",
                })

    # Sort by score descending (original HN ranking is already good, but
    # concurrent fetching scrambles order)
    stories.sort(key=lambda s: s["score"], reverse=True)
    return stories
