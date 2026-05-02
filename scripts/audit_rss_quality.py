#!/usr/bin/env python3
"""Audit RSS feed quality across saved pipeline artifacts."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from morning_digest.config import load_config

_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _ROOT / "output" / "artifacts"
_CONFIG_PATH = _ROOT / "config"


def load_artifacts(
    artifacts_root: Path,
    window_days: int,
    *,
    latest: bool = False,
) -> list[dict]:
    """Load recent raw_sources and enrichment artifacts."""
    if not artifacts_root.exists():
        return []
    directories = sorted(path for path in artifacts_root.iterdir() if path.is_dir())
    if latest:
        directory = _latest_artifact_dir(directories)
        return [_load_artifact_dir(directory)] if directory else []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).date()
    artifacts = []
    for directory in directories:
        try:
            artifact_day = datetime.fromisoformat(directory.name).date()
        except ValueError:
            continue
        if artifact_day < cutoff:
            continue
        artifact = _load_artifact_dir(directory)
        if artifact:
            artifacts.append(artifact)
    return artifacts


def _latest_artifact_dir(directories: list[Path]) -> Path | None:
    valid = []
    for directory in directories:
        try:
            datetime.fromisoformat(directory.name).date()
        except ValueError:
            continue
        if (directory / "raw_sources.json").exists():
            valid.append(directory)
    return max(valid, key=lambda path: path.name) if valid else None


def _load_artifact_dir(directory: Path) -> dict | None:
    raw_path = directory / "raw_sources.json"
    if not raw_path.exists():
        return None
    try:
        rss_items = json.loads(raw_path.read_text(encoding="utf-8")).get("rss", [])
    except json.JSONDecodeError:
        return None

    enrich_records = []
    enrich_path = directory / "enrich_articles.json"
    if enrich_path.exists():
        try:
            enrich_records = json.loads(enrich_path.read_text(encoding="utf-8")).get(
                "records", []
            )
        except json.JSONDecodeError:
            pass
    return {
        "date": directory.name,
        "rss_items": rss_items or [],
        "enrich_records": enrich_records or [],
    }


def compute_feed_metrics(items: list[dict]) -> dict[str, dict]:
    """Return per-feed summary-length metrics."""
    lengths_by_source: dict[str, list[int]] = defaultdict(list)
    empty_by_source: dict[str, int] = defaultdict(int)
    for item in items:
        source = item.get("source", "?")
        length = len(item.get("summary", "") or "")
        lengths_by_source[source].append(length)
        if length == 0:
            empty_by_source[source] += 1

    metrics = {}
    for source, lengths in lengths_by_source.items():
        sorted_lengths = sorted(lengths)
        metrics[source] = {
            "items": len(lengths),
            "mean_chars": int(statistics.mean(lengths)) if lengths else 0,
            "median_chars": int(statistics.median(lengths)) if lengths else 0,
            "p10_chars": _percentile(sorted_lengths, 10),
            "empty_count": empty_by_source[source],
            "empty_rate": empty_by_source[source] / len(lengths) if lengths else 0.0,
        }
    return metrics


def merge_enrich_metrics(feed_metrics: dict[str, dict], records: list[dict]) -> None:
    """Add enrichment status metrics in-place."""
    statuses_by_source: dict[str, list[str]] = defaultdict(list)
    native_lengths: dict[str, list[int]] = defaultdict(list)
    for record in records:
        source = record.get("source", "?")
        statuses_by_source[source].append(record.get("status", ""))
        native_lengths[source].append(int(record.get("native_length") or 0))

    for source, statuses in statuses_by_source.items():
        if source not in feed_metrics:
            continue
        total = len(statuses)
        feed_metrics[source]["enrichment_attempts"] = total
        feed_metrics[source]["success_rate"] = _rate(
            statuses,
            lambda value: value in {"ok", "cache_hit:ok"},
        )
        feed_metrics[source]["paywall_rate"] = _rate(
            statuses, lambda value: value == "paywall"
        )
        feed_metrics[source]["http_error_rate"] = _rate(
            statuses, lambda value: value == "http_error"
        )
        feed_metrics[source]["browser_failure_rate"] = _rate(
            statuses, lambda value: value.startswith("browser_")
        )
        feed_metrics[source]["fetch_cap_skipped"] = sum(
            1 for value in statuses if value == "skipped_fetch_cap"
        )
        feed_metrics[source]["browser_cap_skipped"] = sum(
            1 for value in statuses if value == "skipped_browser_fetch_cap"
        )
        feed_metrics[source]["extraction_failed_rate"] = _rate(
            statuses, lambda value: value == "extraction_failed"
        )
        feed_metrics[source]["normalizer_fallback_rate"] = _rate(
            statuses,
            lambda value: value == "normalizer_fallback"
            or value == "cache_hit:normalizer_fallback",
        )
        feed_metrics[source]["llm_failure_rate"] = _rate(
            statuses,
            lambda value: value == "llm_failed" or value == "cache_hit:llm_failed",
        )
        lengths = native_lengths[source]
        feed_metrics[source]["native_mean_chars"] = (
            int(statistics.mean(lengths)) if lengths else 0
        )
        feed_metrics[source]["native_median_chars"] = (
            int(statistics.median(lengths)) if lengths else 0
        )

    for metric in feed_metrics.values():
        metric.setdefault("enrichment_attempts", 0)
        metric.setdefault("success_rate", None)
        metric.setdefault("paywall_rate", None)
        metric.setdefault("http_error_rate", None)
        metric.setdefault("browser_failure_rate", None)
        metric.setdefault("fetch_cap_skipped", 0)
        metric.setdefault("browser_cap_skipped", 0)
        metric.setdefault("extraction_failed_rate", None)
        metric.setdefault("normalizer_fallback_rate", None)
        metric.setdefault("llm_failure_rate", None)
        metric.setdefault("native_mean_chars", 0)
        metric.setdefault("native_median_chars", 0)


def annotate_with_config(feed_metrics: dict[str, dict], config_path: Path) -> None:
    """Add feed mode/cap/enrichment strategy and health from runtime config."""
    try:
        if config_path.is_dir():
            config = load_config(config_path.parent)
        elif config_path.name == "config.yaml":
            config = load_config(config_path.parent)
        else:
            if not config_path.exists():
                return
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return
    feeds = {feed.get("name"): feed for feed in config.get("rss", {}).get("feeds", [])}
    for source, metric in feed_metrics.items():
        feed = feeds.get(source, {})
        enrich = feed.get("enrich", {}) or {}
        strategy = enrich.get("strategy")
        if not strategy:
            if enrich.get("skip"):
                strategy = "skip"
            elif enrich.get("fetch_article"):
                strategy = "fetch_with_cookies" if enrich.get("cookies_file") else "fetch"
            else:
                strategy = "auto"
        metric["mode"] = feed.get("mode", "rss")
        metric["cap"] = feed.get("cap", "")
        metric["strategy"] = strategy
        metric["health"] = feed.get("health", "active")
        metric["enrich_cfg"] = enrich
        metric["skip_policy"] = enrich.get("skip_reason") or (
            "title_only_ok" if enrich.get("title_only_ok") else ""
        )


def recommend_action(
    items: int,
    median_chars: int,
    empty_rate: float,
    paywall_rate: float | None,
    mode: str,
    enrich_cfg: dict,
    browser_failure_rate: float | None = None,
) -> str:
    """Recommend a feed config action."""
    strategy = enrich_cfg.get("strategy")
    if not strategy:
        if enrich_cfg.get("skip"):
            strategy = "skip"
        elif enrich_cfg.get("fetch_article"):
            strategy = "fetch_with_cookies" if enrich_cfg.get("cookies_file") else "fetch"
        else:
            strategy = "auto"

    has_cookies = bool(enrich_cfg.get("cookies_file"))
    if strategy == "browser_fetch" and browser_failure_rate is not None:
        if browser_failure_rate >= 0.8:
            return "browser_fetch failing; revise wait/policy"
    if strategy == "skip":
        if enrich_cfg.get("title_only_ok"):
            return "ok (title/teaser-only accepted)"
        if median_chars < 80 or empty_rate > 0:
            return "define skip policy or retire"
        return "ok (intentionally skipped)"
    if paywall_rate is not None and paywall_rate >= 0.8:
        if has_cookies:
            return "refresh cookies (paywall rate high)"
        return 'strategy: "skip"'
    if strategy in {"fetch", "fetch_with_cookies"} and (
        paywall_rate is None or paywall_rate < 0.3
    ):
        return "ok (enrichment working)"
    if median_chars == 0 and mode == "html_index":
        return 'strategy: "fetch"'
    if median_chars < 200 or empty_rate > 0.2:
        return 'strategy: "fetch"'
    if items == 0:
        return "retire feed"
    return "ok"


def render_markdown_report(feed_metrics: dict[str, dict]) -> str:
    if not feed_metrics:
        return "# RSS Feed Quality Audit\n\nNo feeds found in window. No artifacts matched.\n"

    lines = [
        "# RSS Feed Quality Audit",
        "",
        "| Feed | Items | Median chars | Empty % | Paywall % | HTTP % | Browser fail % | Normalizer fallback % | Mode | Strategy | Health | Policy | Recommend |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|",
    ]
    for source, metric in sorted(
        feed_metrics.items(), key=lambda item: (item[1]["median_chars"], item[0])
    ):
        rec = recommend_action(
            items=metric["items"],
            median_chars=metric["median_chars"],
            empty_rate=metric["empty_rate"],
            paywall_rate=metric.get("paywall_rate"),
            mode=metric.get("mode", "rss"),
            enrich_cfg=metric.get("enrich_cfg", {}),
            browser_failure_rate=metric.get("browser_failure_rate"),
        )
        lines.append(
            "| {source} | {items} | {median} | {empty} | {paywall} | {http} | {browser} | {fallback} | {mode} | {strategy} | {health} | {policy} | {rec} |".format(
                source=source,
                items=metric["items"],
                median=metric["median_chars"],
                empty=_pct(metric["empty_rate"]),
                paywall=_pct(metric.get("paywall_rate")),
                http=_pct(metric.get("http_error_rate")),
                browser=_pct(metric.get("browser_failure_rate")),
                fallback=_pct(metric.get("normalizer_fallback_rate")),
                mode=metric.get("mode", "rss"),
                strategy=metric.get("strategy", "auto"),
                health=metric.get("health", "active"),
                policy=metric.get("skip_policy", ""),
                rec=rec,
            )
        )
    return "\n".join(lines) + "\n"


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, round((percentile / 100) * (len(values) - 1))))
    return values[index]


def _rate(values: list[str], predicate) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if predicate(value)) / len(values)


def _pct(value: float | None) -> str:
    return "--" if value is None else f"{int(value * 100)}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit RSS feed quality.")
    parser.add_argument("--window", type=int, default=14)
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Audit only the newest artifact directory. --window 0 is an alias.",
    )
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--artifacts-dir", type=str, default=str(_ARTIFACTS_DIR))
    parser.add_argument("--config", type=str, default=str(_CONFIG_PATH))
    args = parser.parse_args()

    latest = args.latest or args.window == 0
    artifacts = load_artifacts(Path(args.artifacts_dir), args.window, latest=latest)
    if not artifacts:
        report = (
            "# RSS Feed Quality Audit\n\n"
            "No artifact directories found under output/artifacts/.\n"
        )
    else:
        items = []
        records = []
        for artifact in artifacts:
            items.extend(artifact["rss_items"])
            records.extend(artifact["enrich_records"])
        metrics = compute_feed_metrics(items)
        merge_enrich_metrics(metrics, records)
        annotate_with_config(metrics, Path(args.config))
        report = render_markdown_report(metrics)

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
