from collections import OrderedDict

from morning_digest.config import load_config
from scripts.stage_model_comparison import (
    MODEL_SPECS,
    comparable_stage_names,
    evaluate_stage_output,
    _resolve_stage_candidate_model_config,
    resolve_model_keys,
)


def test_resolve_model_keys_supports_named_group():
    keys = resolve_model_keys("new")
    assert keys == ["kimi_k2_6", "minimax_m2_7", "qwen3_6_plus", "glm_5_1"]


def test_comparable_stage_names_matches_expected_manifest_subset():
    config = load_config()
    stages = comparable_stage_names(config)
    assert stages == [
        "enrich_articles",
        "compress",
        "analyze_domain",
        "prepare_spiritual_weekly",
        "prepare_spiritual",
        "seams",
        "cross_domain",
        "coverage_gaps",
    ]


def test_evaluate_analyze_domain_scores_schema_like_output():
    outputs = {
        "domain_analysis": {
            "geopolitics": {
                "items": [
                    {
                        "analysis": "My read: Something changed. Watch for follow-through.",
                    }
                ]
            },
            "defense_space": {
                "items": [
                    {
                        "analysis": "My read: Procurement shifted. Watch for contract timing.",
                    }
                ]
            },
            "ai_tech": {
                "items": [
                    {
                        "analysis": "My read: Capability moved. Watch for developer adoption.",
                    }
                ]
            },
            "econ": {
                "items": [
                    {
                        "analysis": "My read: Market signal diverged. Watch for credit spreads.",
                    }
                ]
            },
        },
        "domain_analysis_failures": [],
        "domain_analysis_contract_issues": [],
    }
    context = {"raw_sources": {"rss": [{}] * 20}}
    metrics = evaluate_stage_output("analyze_domain", outputs, context, [], None)  # type: ignore[arg-type]

    assert isinstance(metrics, OrderedDict)
    assert metrics["quality_score"] == 100
    assert metrics["domains_with_items"] == 4
    assert metrics["my_read_pct"] == 1.0
    assert metrics["watch_for_pct"] == 1.0


def test_evaluate_cross_domain_penalizes_invalid_tags():
    outputs = {
        "cross_domain_output": {
            "at_a_glance": [{"tag": "invalid"}],
            "deep_dives": [],
            "cross_domain_connections": [],
            "worth_reading": [],
        },
        "validation_diagnostics": {"issue_count": 1},
        "cross_domain_contract_issues": [{"message": "bad"}],
    }
    metrics = evaluate_stage_output("cross_domain", outputs, {}, [], None)  # type: ignore[arg-type]

    assert metrics["quality_score"] == 45
    assert metrics["invalid_tags"] == 1
    assert metrics["validation_issues"] == 1
    assert metrics["contract_issues"] == 1


def test_stage_candidate_model_config_preserves_stage_tuning():
    config = load_config()
    stage_cfg = next(
        stage for stage in config["pipeline"]["stages"] if stage["name"] == "compress"
    )
    resolved = _resolve_stage_candidate_model_config(
        config,
        stage_cfg,
        "compress",
        MODEL_SPECS["kimi_k2_6"],
    )

    assert resolved["model"] == "accounts/fireworks/models/kimi-k2p6"
    assert resolved["provider"] == "fireworks"
    assert resolved["max_tokens"] == 2000
    assert resolved["temperature"] == 0.2
