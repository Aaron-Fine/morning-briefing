"""Two-turn tests for stages/cross_domain.py."""

import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.cross_domain import run


def _context():
    return {
        "domain_analysis": {
            "geopolitics": {
                "items": [
                    {
                        "headline": "Test headline",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "links": [{"url": "https://example.com/story", "label": "Example"}],
                    }
                ]
            },
            "econ": {"items": [], "market_context": "Fallback market context"},
        },
        "seam_data": {"contested_narratives": [], "coverage_gaps": [], "key_assumptions": []},
        "raw_sources": {"rss": [{"url": "https://example.com/story", "source": "Example"}]},
    }


def _config():
    return {
        "llm": {"provider": "fireworks"},
        "digest": {
            "at_a_glance": {"max_items": 7},
            "deep_dives": {"count": 2},
            "worth_reading": {"count": 3},
        },
    }


@patch("stages.cross_domain.call_llm")
def test_cross_domain_returns_plan_and_output(mock_llm):
    mock_llm.side_effect = [
        {
            "schema_version": 1,
            "cross_domain_connections": [
                {
                    "description": "Connection",
                    "domains": ["geopolitics", "econ"],
                    "entities": ["China"],
                    "rationale": "Why it matters",
                }
            ],
            "deep_dives": [
                {"topic": "Topic 1", "angle": "Angle 1", "why_selected": "Reason 1"},
                {"topic": "Topic 2", "angle": "Angle 2", "why_selected": "Reason 2"},
            ],
            "worth_reading": [
                {"topic": "Read 1", "why_worth_reading": "Worth 1"},
                {"topic": "Read 2", "why_worth_reading": "Worth 2"},
                {"topic": "Read 3", "why_worth_reading": "Worth 3"},
            ],
            "rejected_alternatives": [{"topic": "Other", "reason": "Less important"}],
        },
        {
            "at_a_glance": [],
            "deep_dives": [
                {
                    "headline": "Dive",
                    "body": "<p>Body</p>",
                    "why_it_matters": "Matters",
                    "further_reading": [{"url": "https://example.com/story", "label": "Example: Story"}],
                    "source_depth": "single-source",
                    "domains_bridged": ["geopolitics", "econ"],
                }
            ],
            "cross_domain_connections": [],
            "worth_reading": [
                {
                    "title": "Read 1",
                    "url": "https://example.com/story",
                    "source": "Example",
                    "description": "Desc",
                    "read_time": "10 min",
                }
            ],
        },
    ]

    result = run(_context(), _config())

    assert "cross_domain_plan" in result
    assert result["cross_domain_plan"]["schema_version"] == 1
    assert len(result["cross_domain_plan"]["deep_dives"]) == 2
    assert len(result["cross_domain_plan"]["worth_reading"]) == 3
    assert "cross_domain_output" in result
    assert result["cross_domain_output"]["market_context"] == "Fallback market context"
    assert mock_llm.call_count == 2


@patch("stages.cross_domain.call_llm")
def test_cross_domain_uses_existing_plan_for_from_plan(mock_llm):
    mock_llm.return_value = {
        "at_a_glance": [],
        "deep_dives": [],
        "cross_domain_connections": [],
        "worth_reading": [],
    }
    context = _context()
    context["cross_domain_plan"] = {
        "schema_version": 1,
        "cross_domain_connections": [],
        "deep_dives": [
            {"topic": "Topic 1", "angle": "Angle 1", "why_selected": "Reason 1"},
            {"topic": "Topic 2", "angle": "Angle 2", "why_selected": "Reason 2"},
        ],
        "worth_reading": [
            {"topic": "Read 1", "why_worth_reading": "Worth 1"},
            {"topic": "Read 2", "why_worth_reading": "Worth 2"},
            {"topic": "Read 3", "why_worth_reading": "Worth 3"},
        ],
        "rejected_alternatives": [],
    }
    context["cross_domain_from_plan"] = True

    result = run(context, _config())

    assert result["cross_domain_plan"]["schema_version"] == 1
    assert mock_llm.call_count == 1
    execute_user_content = mock_llm.call_args.args[1]
    assert "=== EDITORIAL PLAN ===" in execute_user_content
    assert "Topic 1" in execute_user_content


@patch("stages.cross_domain.call_llm")
def test_cross_domain_applies_turn_overrides(mock_llm):
    mock_llm.side_effect = [
        {
            "schema_version": 1,
            "cross_domain_connections": [],
            "deep_dives": [],
            "worth_reading": [],
            "rejected_alternatives": [],
        },
        {
            "at_a_glance": [],
            "deep_dives": [],
            "cross_domain_connections": [],
            "worth_reading": [],
        },
    ]

    run(
        _context(),
        _config(),
        {"provider": "fireworks", "model": "base", "temperature": 0.3},
        stage_cfg={
            "turns": {
                "plan": {"temperature": 0.4, "max_tokens": 4000},
                "execute": {"temperature": 0.2, "max_tokens": 9000},
            }
        },
    )

    first_cfg = mock_llm.call_args_list[0].args[2]
    second_cfg = mock_llm.call_args_list[1].args[2]
    assert first_cfg["temperature"] == 0.4
    assert first_cfg["max_tokens"] == 4000
    assert second_cfg["temperature"] == 0.2
    assert second_cfg["max_tokens"] == 9000
