#!/usr/bin/env python3
"""Validate RSS/Atom feed URLs before adding to runtime config.

Usage:
    python scripts/validate_new_feeds.py                    # validate candidate feeds
    python scripts/validate_new_feeds.py --config           # validate all feeds in config/sources.yaml
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feedparser
import requests
from morning_digest.config import load_config

from sources.rss_feeds import _items_from_html_index, _parse_feed_date


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

    # Find most recent entry date.
    latest = ""
    latest_dt = None
    for entry in feed.entries:
        parsed = _parse_feed_date(entry)
        if parsed and (latest_dt is None or parsed > latest_dt):
            latest_dt = parsed
    if latest_dt:
        latest = latest_dt.isoformat()

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
    config = load_config(Path(__file__).parent.parent)
    return config.get("rss", {}).get("feeds", [])


def _previous_commit_feeds() -> list[dict] | None:
    """Load feeds from the previous commit of config/sources.yaml."""
    import subprocess
    repo = Path(__file__).parent.parent
    try:
        proc = subprocess.run(
            ["git", "show", "HEAD:config/sources.yaml"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        # Parse YAML manually to avoid full PyYAML dependency if possible,
        # but we already depend on yaml through load_config. Re-use it.
        import yaml
        data = yaml.safe_load(proc.stdout)
        return data.get("rss", {}).get("feeds", [])
    except Exception:
        return None


def _find_new_feeds() -> list[dict]:
    """Return feed entries that are present now but were absent in the previous commit."""
    current = _load_configured_feeds()
    previous = _previous_commit_feeds()
    if previous is None:
        return []
    prev_urls = {f.get("url", "") for f in previous}
    return [f for f in current if f.get("url", "") not in prev_urls]


def _latest_is_recent(latest: str, *, days: int = 7) -> bool:
    if not latest:
        return False
    try:
        parsed = datetime.fromisoformat(latest.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= datetime.now(timezone.utc) - timedelta(days=days)


def _validate_new_feed_rules(
    feed: dict,
    desk_categories: set[str],
    validation_result: dict | None = None,
) -> list[str]:
    """Return a list of rule violations for a new feed (beyond HTTP/parser checks)."""
    errors = []
    cat = feed.get("category", "")
    if not cat:
        errors.append("missing category")
    elif cat not in desk_categories:
        errors.append(f"category '{cat}' not routed to any desk")
    health = feed.get("health", "")
    valid_health = {"active", "headline_radar", "low_frequency", "enrichment_required", "degraded", "broken"}
    if not health:
        errors.append("missing health field")
    elif health not in valid_health:
        errors.append(f"invalid health '{health}'")
    if validation_result and validation_result.get("status") == "OK":
        latest = validation_result.get("latest", "")
        recency_exempt = health in {"low_frequency", "headline_radar"}
        if not recency_exempt and not _latest_is_recent(latest):
            errors.append("no item dated within the last 7 days")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate RSS/Atom feed URLs")
    parser.add_argument("--config", action="store_true", help="Validate all feeds from config/sources.yaml")
    parser.add_argument("--category", type=str, help="Validate only feeds in this category")
    parser.add_argument("--new-only", action="store_true", help="Validate only feeds added since the last commit")
    args = parser.parse_args()

    if args.new_only:
        feeds = _find_new_feeds()
        if not feeds:
            print("No new feeds detected since the last commit.")
            sys.exit(0)
    else:
        feeds = _load_configured_feeds()
        if args.category:
            feeds = [f for f in feeds if f.get("category") == args.category]

    # Resolve desk categories for routing validation
    from stages.analyze_domain import _resolve_domain_configs
    from stages.prepare_local import CONSUMED_RSS_CATEGORIES
    config = load_config(Path(__file__).parent.parent)
    desk_categories = {
        cat
        for desk in _resolve_domain_configs(config).values()
        for cat in desk.get("categories", set())
    }
    desk_categories |= CONSUMED_RSS_CATEGORIES

    print(f"Validating {len(feeds)} feeds...\n")
    results, failures = validate_feeds(feeds)

    # Apply new-feed rule checks
    for r, feed in zip(results, feeds):
        rule_errors = _validate_new_feed_rules(feed, desk_categories, r)
        if rule_errors:
            r["status"] = "FAIL"
            r["error"] = "; ".join(rule_errors)
            failures += 1

    print_table(results)

    sys.exit(1 if failures > 0 else 0)


if __name__ == "__main__":
    main()
