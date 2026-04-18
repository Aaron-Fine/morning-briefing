"""Focused tests for the two-turn seams stage behavior."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.seams import run


@patch("stages.seams.call_llm")
def test_seams_returns_diagnostic_scan(mock_llm):
    mock_llm.side_effect = [
        {
            "schema_version": 1,
            "tensions": [{"topic": "Topic"}],
            "absences": [{"topic": "Gap"}],
            "assumptions": [{"topic": "Assumption"}],
        },
        {
            "contested_narratives": [],
            "coverage_gaps": [],
            "key_assumptions": [],
        },
    ]

    result = run(
        {"domain_analysis": {}, "raw_sources": {}, "compressed_transcripts": []},
        {"llm": {}},
    )

    assert result["seam_scan"] == {
        "schema_version": 1,
        "tensions": [{"topic": "Topic"}],
        "absences": [{"topic": "Gap"}],
        "assumptions": [{"topic": "Assumption"}],
    }


@patch("stages.seams.call_llm")
def test_seams_applies_turn_overrides(mock_llm):
    mock_llm.side_effect = [
        {"schema_version": 1, "tensions": [], "absences": [], "assumptions": []},
        {"contested_narratives": [], "coverage_gaps": [], "key_assumptions": []},
    ]
    stage_cfg = {
        "turns": {
            "scan": {"max_tokens": 4000, "temperature": 0.4},
            "synthesis": {"max_tokens": 5000, "temperature": 0.3},
        }
    }
    model_config = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "max_tokens": 6000,
        "temperature": 0.2,
    }

    run(
        {"domain_analysis": {}, "raw_sources": {}, "compressed_transcripts": []},
        {"llm": {}},
        model_config=model_config,
        stage_cfg=stage_cfg,
    )

    scan_call = mock_llm.call_args_list[0]
    synthesis_call = mock_llm.call_args_list[1]
    assert scan_call.args[2]["max_tokens"] == 4000
    assert scan_call.args[2]["temperature"] == 0.4
    assert synthesis_call.args[2]["max_tokens"] == 5000
    assert synthesis_call.args[2]["temperature"] == 0.3


@patch("stages.seams.call_llm")
def test_seams_retries_turn_without_stream(mock_llm):
    mock_llm.side_effect = [
        Exception("bad json"),
        {"schema_version": 1, "tensions": [], "absences": [], "assumptions": []},
        {"contested_narratives": [], "coverage_gaps": [], "key_assumptions": []},
    ]

    run(
        {"domain_analysis": {}, "raw_sources": {}, "compressed_transcripts": []},
        {"llm": {}},
        model_config={"provider": "anthropic", "model": "claude-sonnet-4-6"},
    )

    assert mock_llm.call_args_list[0].kwargs["stream"] is True
    assert mock_llm.call_args_list[1].kwargs["stream"] is False
