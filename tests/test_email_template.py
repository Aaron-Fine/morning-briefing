"""Tests for templates/email_template.py."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from templates.email_template import render_email


def _base_data(**overrides):
    data = {
        "date_display": "Tuesday, Apr 21",
        "generated_at": "2026-04-21T07:00:00",
        "rss_source_names": "Example",
        "yt_source_names": "",
    }
    data.update(overrides)
    return data


def test_email_css_uses_mobile_padding_and_larger_tags():
    html = render_email(_base_data())

    assert "@import url(" not in html
    assert "@media (max-width: 480px)" in html
    assert ".section { padding: 22px 16px; }" in html
    assert ".tag { font-size: 11px;" in html


def test_markets_render_as_table_not_flex_strip():
    html = render_email(
        _base_data(
            markets=[
                {
                    "label": "SPY",
                    "price": "500.00",
                    "direction": "up",
                    "change_pct": 1.2,
                }
            ]
        )
    )

    assert 'class="markets-table"' in html
    assert 'class="market-cell"' in html
    assert 'class="markets"' not in html
    assert "table-layout: fixed;" in html


def test_scan_header_renders_as_table_not_flex_container():
    html = render_email(
        _base_data(
            at_a_glance=[
                {
                    "tag": "tech",
                    "tag_label": "Technology",
                    "headline": "A durable headline",
                    "facts": "Reported fact.",
                    "analysis": "",
                    "cross_domain_note": "",
                    "links": [],
                }
            ]
        )
    )

    assert 'class="scan-header-table"' in html
    assert 'class="scan-tag-cell"' in html
    assert 'class="scan-headline-cell"' in html
    assert 'class="scan-header"' not in html


def test_further_reading_links_have_separating_rows():
    html = render_email(
        _base_data(
            deep_dives=[
                {
                    "headline": "Deep dive",
                    "body": "Body",
                    "why_it_matters": "",
                    "further_reading": [
                        {"url": "https://example.com/a", "label": "A", "source": "One"},
                        {"url": "https://example.com/b", "label": "B", "source": "Two"},
                    ],
                }
            ]
        )
    )

    assert html.count('class="fr-item"') == 2
    assert ".fr-item { padding: 5px 0; border-top: 1px dotted var(--border); }" in html


def test_stage_failures_render_in_footer_when_present():
    html = render_email(
        _base_data(
            stage_failures=[
                {"stage": "prepare_weather", "error": "timeout"},
                {"stage": "coverage_gaps", "error": "bad response"},
            ]
        )
    )

    assert "Pipeline notices:" in html
    assert "prepare_weather" in html
    assert "coverage_gaps" in html


def test_thread_voice_uses_badge_style():
    html = render_email(
        _base_data(
            at_a_glance=[
                {
                    "tag": "tech",
                    "tag_label": "Technology",
                    "headline": "A durable headline",
                    "facts": "",
                    "analysis": "",
                    "cross_domain_note": "A thread note.",
                    "links": [],
                }
            ]
        )
    )

    assert "scan-voice-thread" in html
    assert ".scan-voice-thread   { color: var(--accent-seam); background: #f7efe6; }" in html
