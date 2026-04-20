"""Tests for article content selection helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.article_content import (
    best_native_text,
    needs_distillation,
    needs_fetch,
    resolve_strategy,
)


def test_best_native_text_prefers_preserved_rss_body():
    item = {
        "_rss_body": "<p>Full native body</p>",
        "content": [{"value": "Content value"}],
        "summary": "Short teaser",
    }
    assert best_native_text(item) == ("Full native body", "rss_body")


def test_best_native_text_uses_content_before_summary():
    item = {"content": [{"value": "<p>Full content</p>"}], "summary": "Teaser"}
    assert best_native_text(item) == ("Full content", "content")


def test_best_native_text_falls_back_to_summary_then_description():
    assert best_native_text({"summary": "Summary"}) == ("Summary", "summary")
    assert best_native_text({"summary": " ", "description": "Description"}) == (
        "Description",
        "description",
    )


def test_best_native_text_ignores_blank_and_html_only_values():
    assert best_native_text({"content": [{"value": "<p> </p>"}], "summary": ""}) == (
        "",
        "none",
    )


def test_resolve_strategy_supports_explicit_and_legacy_flags():
    assert resolve_strategy({"enrich": {"strategy": "rss_only"}}) == "rss_only"
    assert resolve_strategy({"enrich": {"strategy": "skip"}}) == "skip"
    assert resolve_strategy({"enrich": {"skip": True}}) == "skip"
    assert resolve_strategy({"enrich": {"fetch_article": True}}) == "fetch"
    assert (
        resolve_strategy(
            {"enrich": {"fetch_article": True, "cookies_file": "cookies/a.txt"}}
        )
        == "fetch_with_cookies"
    )
    assert resolve_strategy({}) == "auto"


def test_needs_fetch_respects_strategy_and_length():
    assert needs_fetch("", "auto", 200) is True
    assert needs_fetch("x" * 250, "auto", 200) is False
    assert needs_fetch("x" * 250, "fetch", 200) is True
    assert needs_fetch("", "rss_only", 200) is False
    assert needs_fetch("", "skip", 200) is False


def test_needs_distillation_for_long_text_only():
    assert needs_distillation("x" * 799, 800) is False
    assert needs_distillation("x" * 800, 800) is True
