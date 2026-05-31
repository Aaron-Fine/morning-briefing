import logging
from unittest.mock import MagicMock, patch
from morning_digest.llm import call_llm


def test_runner_folds_llm_usage():
    import pipeline
    from morning_digest.llm import LLMUsage
    run_meta = {"metrics": {"stages": {}, "overrides": {}, "totals": {}}}
    outputs = {"foo": [1, 2, 3], "llm_usage": [LLMUsage("m", "fireworks", 100, 20, 5)]}
    remaining = pipeline._fold_stage_metrics(
        run_meta, "seams", outputs, latency_s=1.2, retries=0
    )
    assert "llm_usage" not in remaining          # reserved key popped
    stage = run_meta["metrics"]["stages"]["seams"]
    assert stage["tokens_in"] == 100 and stage["tokens_out"] == 20
    assert stage["tokens_cached"] == 5
    assert stage["latency_s"] == 1.2 and stage["retries"] == 0
    assert run_meta["metrics"]["totals"]["tokens_in"] == 100


def test_runner_folds_override_counts():
    import pipeline
    rm = {"metrics": {"stages": {}, "overrides": {}, "totals": {}}}
    pipeline._fold_stage_metrics(rm, "cross_domain",
        {"override_counts": {"normalize_tag": 3}}, latency_s=0.1, retries=0)
    pipeline._fold_stage_metrics(rm, "analyze_domain",
        {"override_counts": {"rebalance_categories": 2, "normalize_tag": 1}}, latency_s=0.1, retries=0)
    assert rm["metrics"]["overrides"] == {"normalize_tag": 4, "rebalance_categories": 2}


@patch("morning_digest.llm._fireworks_client")
def test_call_llm_emits_progress(mock_client, caplog):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = '{"ok": 1}'
    resp.usage.prompt_tokens = 5
    resp.usage.completion_tokens = 2
    mock_client.return_value.chat.completions.create.return_value = resp
    with caplog.at_level(logging.INFO):
        call_llm("s", "u", {"provider": "fireworks", "model": "m", "max_tokens": 100,
                            "_obs": {"stage": "seams"}}, stream=False)
    msgs = " ".join(r.message for r in caplog.records)
    assert "seams m: start" in msgs
