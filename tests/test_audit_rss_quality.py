"""Tests for RSS feed quality audit."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.audit_rss_quality import (
    compute_feed_metrics,
    load_artifacts,
    merge_enrich_metrics,
    recommend_action,
    render_markdown_report,
)


def _write_artifact(root, date_str, rss_items, enrich_records=None):
    directory = root / date_str
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw_sources.json").write_text(
        json.dumps({"rss": rss_items}), encoding="utf-8"
    )
    if enrich_records is not None:
        (directory / "enrich_articles.json").write_text(
            json.dumps({"records": enrich_records}), encoding="utf-8"
        )


def test_compute_feed_metrics_counts_empty_and_median():
    metrics = compute_feed_metrics(
        [
            {"source": "A", "summary": ""},
            {"source": "A", "summary": "x" * 100},
            {"source": "A", "summary": "x" * 300},
        ]
    )["A"]
    assert metrics["items"] == 3
    assert metrics["empty_rate"] == pytest.approx(1 / 3)
    assert metrics["median_chars"] == 100


def test_merge_enrich_metrics_keeps_http_separate_from_paywall():
    metrics = {"A": {"items": 3, "median_chars": 10, "empty_rate": 0}}
    merge_enrich_metrics(
        metrics,
        [
            {"source": "A", "status": "paywall", "native_length": 0},
            {"source": "A", "status": "http_error", "native_length": 0},
            {"source": "A", "status": "ok", "native_length": 100},
        ],
    )
    assert metrics["A"]["paywall_rate"] == pytest.approx(1 / 3)
    assert metrics["A"]["http_error_rate"] == pytest.approx(1 / 3)


def test_recommend_action_uses_strategy_language():
    rec = recommend_action(5, 0, 1.0, None, "html_index", {})
    assert 'strategy: "fetch"' == rec
    rec = recommend_action(20, 40, 0.0, 0.95, "rss", {})
    assert "skip" in rec
    rec = recommend_action(20, 400, 0.0, None, "rss", {"strategy": "skip"})
    assert "intentionally skipped" in rec


def test_load_artifacts_empty_root_returns_empty_list(tmp_path):
    assert load_artifacts(tmp_path, 14) == []


def test_load_artifacts_reads_raw_and_enrichment(tmp_path):
    _write_artifact(
        tmp_path,
        "2026-04-19",
        [{"source": "A", "summary": "x"}],
        [{"source": "A", "status": "ok"}],
    )
    loaded = load_artifacts(tmp_path, 14)
    assert len(loaded) == 1
    assert loaded[0]["rss_items"][0]["source"] == "A"
    assert loaded[0]["enrich_records"][0]["status"] == "ok"


def test_load_artifacts_latest_reads_newest_artifact(tmp_path):
    _write_artifact(tmp_path, "2026-04-18", [{"source": "Old", "summary": "x"}])
    _write_artifact(tmp_path, "2026-04-19", [{"source": "New", "summary": "x"}])
    loaded = load_artifacts(tmp_path, 0, latest=True)
    assert len(loaded) == 1
    assert loaded[0]["date"] == "2026-04-19"
    assert loaded[0]["rss_items"][0]["source"] == "New"


def test_render_markdown_report_outputs_rows():
    report = render_markdown_report(
        {
            "A": {
                "items": 1,
                "median_chars": 0,
                "empty_rate": 1.0,
                "paywall_rate": None,
                "http_error_rate": None,
                "mode": "html_index",
                "strategy": "auto",
                "enrich_cfg": {},
            }
        }
    )
    assert "| Feed |" in report
    assert "| A |" in report


def test_recommend_action_flags_thin_skip_without_policy():
    rec = recommend_action(5, 0, 1.0, None, "rss", {"strategy": "skip"})
    assert rec == "define skip policy or retire"


def test_recommend_action_accepts_title_only_skip_policy():
    rec = recommend_action(
        5,
        0,
        1.0,
        None,
        "rss",
        {"strategy": "skip", "title_only_ok": True},
    )
    assert rec == "ok (title/teaser-only accepted)"


def test_recommend_action_flags_browser_fetch_failures():
    rec = recommend_action(
        8,
        0,
        1.0,
        None,
        "rss",
        {"strategy": "browser_fetch"},
        browser_failure_rate=1.0,
    )
    assert rec == "browser_fetch failing; revise wait/policy"
