#!/usr/bin/env python3
"""Validate RSS/Atom feed URLs before adding to config.yaml.

Usage:
    python scripts/validate_new_feeds.py                    # validate candidate feeds
    python scripts/validate_new_feeds.py --config           # validate all feeds in config.yaml
    python scripts/validate_new_feeds.py --category energy-materials  # validate one category

Checks each URL:
  - HTTP fetch succeeds
  - feedparser finds valid XML
  - At least one entry with a non-empty title exists
  - Prints a summary table with status and most recent entry date

Exits non-zero if any feed fails.
"""

import argparse
import sys
from pathlib import Path

import feedparser
import requests
import yaml

from sources.rss_feeds import _items_from_html_index


def _fetch_feed(url: str, timeout: int = 15) -> dict:
    """Fetch and parse a feed URL. Returns a result dict."""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "MorningDigest/1.0"})
        resp.raise_for_status()
    except Exception as e:
        return {"ok": False, "error": f"HTTP error: {e}", "entries": 0, "latest": ""}

    feed = feedparser.parse(resp.text)
    if feed.bozo and not feed.entries:
        return {"ok": False, "error": f"Parse error: {feed.bozo_exception}", "entries": 0, "latest": ""}

    if not feed.entries:
        return {"ok": False, "error": "No entries found", "entries": 0, "latest": ""}

    # Check for at least one entry with a non-empty title
    has_title = any(e.get("title", "").strip() for e in feed.entries)
    if not has_title:
        return {"ok": False, "error": "No entries with titles", "entries": len(feed.entries), "latest": ""}

    # Find most recent entry date
    latest = ""
    for entry in feed.entries[:5]:
        for date_field in ("published", "updated", "created"):
            if entry.get(date_field):
                latest = entry[date_field][:25]
                break
        if latest:
            break

    return {"ok": True, "error": "", "entries": len(feed.entries), "latest": latest}


def _fetch_html_index(feed: dict, timeout: int = 15) -> dict:
    try:
        resp = requests.get(
            feed["url"],
            timeout=timeout,
            headers={
                "User-Agent": "MorningDigest/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        resp.raise_for_status()
    except Exception as e:
        return {"ok": False, "error": f"HTTP error: {e}", "entries": 0, "latest": ""}

    items = _items_from_html_index(feed, resp.content)
    if not items:
        return {"ok": False, "error": "No article links found", "entries": 0, "latest": ""}

    return {"ok": True, "error": "", "entries": len(items), "latest": ""}


def validate_feeds(feeds: list[dict]) -> tuple[list[dict], int]:
    """Validate a list of feed dicts. Returns (results, failure_count)."""
    results = []
    failures = 0

    for feed in feeds:
        name = feed.get("name", "?")
        url = feed.get("url", "")
        category = feed.get("category", "?")

        print(f"  Checking {name}...", end=" ", flush=True)
        if feed.get("mode") == "html_index":
            result = _fetch_html_index(feed)
        else:
            result = _fetch_feed(url)

        status = "OK" if result["ok"] else "FAIL"
        if not result["ok"]:
            failures += 1
            print(f"{status} ({result['error']})")
        else:
            print(f"{status} ({result['entries']} entries, latest: {result['latest']})")

        results.append({
            "name": name,
            "url": url,
            "category": category,
            "status": status,
            "entries": result["entries"],
            "latest": result["latest"],
            "error": result["error"],
        })

    return results, failures


def print_table(results: list[dict]) -> None:
    """Print a summary table."""
    print("\n" + "=" * 100)
    print(f"{'Name':<40} {'Category':<20} {'Status':<6} {'Entries':<8} {'Latest':<25}")
    print("-" * 100)
    for r in results:
        print(f"{r['name']:<40} {r['category']:<20} {r['status']:<6} {r['entries']:<8} {r['latest']:<25}")
    print("=" * 100)

    ok = sum(1 for r in results if r["status"] == "OK")
    fail = sum(1 for r in results if r["status"] == "FAIL")
    print(f"\nTotal: {len(results)} feeds — {ok} OK, {fail} FAILED")

    if fail > 0:
        print("\nFailed feeds:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"  - {r['name']}: {r['error']}")


def _load_configured_feeds() -> list[dict]:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config.get("rss", {}).get("feeds", [])


def main():
    parser = argparse.ArgumentParser(description="Validate RSS/Atom feed URLs")
    parser.add_argument("--config", action="store_true", help="Validate all feeds from config.yaml")
    parser.add_argument("--category", type=str, help="Validate only feeds in this category")
    args = parser.parse_args()

    if args.config:
        feeds = _load_configured_feeds()
        if args.category:
            feeds = [f for f in feeds if f.get("category") == args.category]
    else:
        feeds = _load_configured_feeds()
        if args.category:
            feeds = [f for f in feeds if f.get("category") == args.category]

    print(f"Validating {len(feeds)} feeds...\n")
    results, failures = validate_feeds(feeds)
    print_table(results)

    sys.exit(1 if failures > 0 else 0)


if __name__ == "__main__":
    main()
