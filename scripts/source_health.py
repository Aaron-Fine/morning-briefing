#!/usr/bin/env python3
"""Source health computation and reporting.

Computes per-feed health status from config classification + empirical artifact
data, writes a source_health.json artifact each run, and provides a CLI roll-up.

Health statuses (from config/sources.yaml `health:` field):
  active (default): standard handling
  headline_radar: awareness-only, no fetch/browser enrichment
  low_frequency: empty 24-48h windows expected, fewer items normal
  enrichment_required: RSS body unreliable, prefer fetch/browser-fetch
  degraded: feed failing or partially working
  broken: skipped at fetch time
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from morning_digest.config import load_config
from scripts.audit_rss_quality import (
    _latest_artifact_dir,
    load_artifacts,
    merge_enrich_metrics,
    render_markdown_report,
    compute_feed_metrics,
    _pct,
    _rate,
    _percentile,
)

_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _ROOT / "output" / "artifacts"

_VALID_HEALTHS = {
    "active",
    "headline_radar",
    "low_frequency",
    "enrichment_required",
    "degraded",
    "broken",
}


def _load_feed_healths(config: dict) -> dict[str, str]:
    """Return mapping feed_name -> health status from config."""
    return {
        f.get("name", ""): f.get("health", "active")
        for f in config.get("rss", {}).get("feeds", [])
        if f.get("name")
    }


def compute_source_health(
    config: dict,
    artifacts_root: Path | None = None,
    window_days: int = 14,
) -> dict:
    """Compute source_health artifact for the current or most recent run.

    Returns dict:
      {
        "schema_version": 1,
        "date": "YYYY-MM-DD",
        "feeds": [
          {
            "name": str,
            "health": str,          # from config
            "computed_health": str, # empirical override if any
            "items": int,
            "median_chars": int,
            "empty_rate": float,
            "enrichment_success_rate": float | None,
            "normalizer_fallback_rate": float | None,
            "last_nonempty_date": str | None,
            "observations": [str],
          }
        ]
      }
    """
    artifacts_root = artifacts_root or _ARTIFACTS_DIR
    feed_healths = _load_feed_healths(config)

    # Load latest artifact only for per-run health snapshot
    latest_dir = _latest_artifact_dir(
        sorted(path for path in artifacts_root.iterdir() if path.is_dir())
        if artifacts_root.exists()
        else []
    )
    run_date = latest_dir.name if latest_dir else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load windowed artifacts for trend data
    artifacts = load_artifacts(artifacts_root, window_days, latest=False)
    all_items = []
    all_records = []
    for artifact in artifacts:
        all_items.extend(artifact.get("rss_items", []))
        all_records.extend(artifact.get("enrich_records", []))

    metrics = compute_feed_metrics(all_items)
    merge_enrich_metrics(metrics, all_records)

    # Compute last non-empty date per feed
    last_nonempty: dict[str, str] = {}
    for artifact in sorted(artifacts, key=lambda a: a["date"]):
        for item in artifact.get("rss_items", []):
            source = item.get("source", "")
            if source and source not in last_nonempty:
                last_nonempty[source] = artifact["date"]

    feeds = []
    for name in sorted(feed_healths.keys()):
        health = feed_healths[name]
        metric = metrics.get(name, {})
        items = metric.get("items", 0)
        median_chars = metric.get("median_chars", 0)
        empty_rate = metric.get("empty_rate", 0.0)
        success_rate = metric.get("success_rate")
        fallback_rate = metric.get("normalizer_fallback_rate")
        paywall_rate = metric.get("paywall_rate")
        http_error_rate = metric.get("http_error_rate")

        observations = []
        computed_health = health

        if items == 0:
            observations.append(f"Zero items in {window_days}-day window")
            if health == "active":
                computed_health = "degraded"
        elif items <= 3:
            observations.append(f"Very low volume ({items} items in {window_days} days)")
            if health == "active":
                computed_health = "low_frequency"

        if median_chars < 100 and items > 0:
            observations.append(f"Short RSS bodies (median {median_chars} chars)")
            if health in ("active", "low_frequency"):
                computed_health = "enrichment_required"

        if fallback_rate is not None and fallback_rate >= 0.5:
            observations.append(
                f"High normalizer fallback rate ({_pct(fallback_rate)})"
            )
            if health in ("active", "low_frequency"):
                computed_health = "enrichment_required"

        if http_error_rate is not None and http_error_rate >= 0.5:
            observations.append(f"High HTTP error rate ({_pct(http_error_rate)})")
            if health in ("active", "low_frequency"):
                computed_health = "degraded"

        if paywall_rate is not None and paywall_rate >= 0.8:
            observations.append(f"High paywall rate ({_pct(paywall_rate)})")

        feeds.append(
            {
                "name": name,
                "health": health,
                "computed_health": computed_health,
                "items": items,
                "median_chars": median_chars,
                "empty_rate": round(empty_rate, 2),
                "enrichment_success_rate": (
                    round(success_rate, 2) if success_rate is not None else None
                ),
                "normalizer_fallback_rate": (
                    round(fallback_rate, 2) if fallback_rate is not None else None
                ),
                "last_nonempty_date": last_nonempty.get(name),
                "observations": observations,
            }
        )

    return {
        "schema_version": 1,
        "date": run_date,
        "window_days": window_days,
        "feeds": feeds,
    }


def render_health_cli_table(health_report: dict) -> str:
    """Render a human-readable roll-up of all feeds' health."""
    lines = [
        "# Source Health Roll-up",
        "",
        f"Date: {health_report['date']}  (window: {health_report['window_days']} days)",
        "",
        "| Feed | Config health | Computed | Items | Median chars | Last non-empty | Observations |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for feed in health_report["feeds"]:
        obs = "; ".join(feed["observations"]) if feed["observations"] else "—"
        lines.append(
            f"| {feed['name']} | {feed['health']} | {feed['computed_health']} | "
            f"{feed['items']} | {feed['median_chars']} | "
            f"{feed['last_nonempty_date'] or 'never'} | {obs} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Source health monitor")
    parser.add_argument("--window", type=int, default=14)
    parser.add_argument("--artifacts-dir", type=str, default=str(_ARTIFACTS_DIR))
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Markdown")
    args = parser.parse_args()

    config = load_config(_ROOT)
    report = compute_source_health(
        config,
        artifacts_root=Path(args.artifacts_dir),
        window_days=args.window,
    )

    if args.json:
        text = json.dumps(report, indent=2, default=str)
    else:
        text = render_health_cli_table(report)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
