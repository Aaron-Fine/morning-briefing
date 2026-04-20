"""Focused tests for per-item seam annotations."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.seams import run


@patch("stages.seams.call_llm")
def test_seams_returns_annotation_artifact(mock_llm):
    mock_llm.side_effect = [
        {
            "schema_version": 1,
            "candidates": [
                {
                    "item_id": "geo-1",
                    "seam_type": "framing_divergence",
                    "candidate_one_line": "The non-Western read: this is escalation.",
                    "possible_evidence": [],
                    "why_it_might_matter": "Cost-bearing frame",
                    "drop_if_weak_reason": "",
                }
            ],
            "cross_domain_candidates": [],
        },
        {
            "per_item": [
                {
                    "item_id": "geo-1",
                    "seam_type": "framing_divergence",
                    "one_line": "The non-Western read: this is escalation.",
                    "evidence": [
                        {"source": "A", "excerpt": "escalation", "framing": "risk"},
                        {"source": "B", "excerpt": "signal", "framing": "deterrence"},
                    ],
                    "confidence": "high",
                }
            ],
            "cross_domain": [],
        },
    ]

    result = run(
        {
            "domain_analysis": {
                "geopolitics": {"items": [{"item_id": "geo-1", "headline": "Story"}]}
            },
            "raw_sources": {},
            "compressed_transcripts": [],
        },
        {"llm": {}},
    )

    assert result["seam_candidates"]["candidates"][0]["item_id"] == "geo-1"
    assert result["seam_annotations"]["per_item"][0]["item_id"] == "geo-1"
    assert result["seam_data"]["seam_count"] == 1


@patch("stages.seams.call_llm")
def test_seams_retries_annotation_call_without_stream(mock_llm):
    mock_llm.side_effect = [
        {"schema_version": 1, "candidates": [], "cross_domain_candidates": []},
        Exception("bad json"),
        {"per_item": [], "cross_domain": []},
    ]

    run(
        {"domain_analysis": {}, "raw_sources": {}, "compressed_transcripts": []},
        {"llm": {}},
        model_config={
            "provider": "fireworks",
            "model": "accounts/fireworks/models/minimax-m2p7",
        },
    )

    assert mock_llm.call_args_list[1].kwargs["stream"] is True
    assert mock_llm.call_args_list[2].kwargs["stream"] is False


@patch("stages.seams.call_llm")
def test_seams_applies_turn_overrides(mock_llm):
    mock_llm.side_effect = [
        {"schema_version": 1, "candidates": [], "cross_domain_candidates": []},
        {"per_item": [], "cross_domain": []},
    ]
    stage_cfg = {
        "turns": {
            "candidates": {"max_tokens": 6000, "temperature": 0.4},
            "annotations": {"max_tokens": 8192, "temperature": 0.3},
        }
    }
    model_config = {"provider": "anthropic", "max_tokens": 5000, "temperature": 0.2}

    run(
        {"domain_analysis": {}, "raw_sources": {}, "compressed_transcripts": []},
        {"llm": {}},
        model_config=model_config,
        stage_cfg=stage_cfg,
    )

    assert mock_llm.call_args_list[0].args[2]["max_tokens"] == 6000
    assert mock_llm.call_args_list[0].args[2]["temperature"] == 0.4
    assert mock_llm.call_args_list[1].args[2]["max_tokens"] == 8192
    assert mock_llm.call_args_list[1].args[2]["temperature"] == 0.3
