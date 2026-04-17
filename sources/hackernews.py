"""Fetch top stories from Hacker News (no API key required)."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from sources._http import http_get_json

log = logging.getLogger(__name__)

HN_API = "https://hacker-news.firebaseio.com/v0"


def fetch_hackernews(config: dict) -> list[dict]:
    """Return top HN stories with title, url, score, and comment count.

    Returns list of dicts: {title, url, score, comments, hn_url}
    """
    hn_config = config.get("hackernews", {})
    count = hn_config.get("top_stories", 15)

    top = http_get_json(f"{HN_API}/topstories.json", timeout=10, label="HN topstories")
    if top is None:
        return []
    story_ids = top[:count]

    stories = []

    def _fetch_item(sid):
        return http_get_json(f"{HN_API}/item/{sid}.json", timeout=10, label=f"HN item {sid}")

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

    # Sort by score descending (concurrent fetching scrambles original order)
    stories.sort(key=lambda s: s["score"], reverse=True)
    return stories
