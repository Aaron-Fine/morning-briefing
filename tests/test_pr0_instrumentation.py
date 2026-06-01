import logging
from unittest.mock import MagicMock, patch
from morning_digest.llm import call_llm, LLMUsage
import pipeline


def test_runner_folds_llm_usage():
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
    rm = {"metrics": {"stages": {}, "overrides": {}, "totals": {}}}
    pipeline._fold_stage_metrics(rm, "cross_domain",
        {"override_counts": {"normalize_tag": 3}}, latency_s=0.1, retries=0)
    pipeline._fold_stage_metrics(rm, "analyze_domain",
        {"override_counts": {"rebalance_categories": 2, "normalize_tag": 1}}, latency_s=0.1, retries=0)
    assert rm["metrics"]["overrides"] == {"normalize_tag": 4, "rebalance_categories": 2}


def test_fold_records_items_out():
    rm = {"metrics": {"stages": {}, "overrides": {}, "totals": {}}}
    pipeline._fold_stage_metrics(rm, "collect",
        {"raw_sources": {"rss": [1, 2, 3]}, "extra": [9]}, latency_s=0.1, retries=0)
    items_out = rm["metrics"]["stages"]["collect"]["items_out"]
    assert items_out["extra"] == 1
    assert items_out["raw_sources.rss"] == 3


def test_fold_routes_domain_research():
    rm = {"metrics": {"stages": {}, "overrides": {}, "totals": {}}}
    pipeline._fold_stage_metrics(rm, "analyze_domain",
        {"domain_research_metrics": {"fired": 2, "articles_fetched": 7, "changed_output": True}},
        latency_s=0.1, retries=0)
    assert rm["metrics"]["domain_research"] == {"fired": 2, "articles_fetched": 7, "changed_output": True}


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


@patch("morning_digest.llm._fireworks_client")
def test_capture_prompts_writes_files(mock_client, tmp_path):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "{}"
    resp.usage.prompt_tokens = 1
    resp.usage.completion_tokens = 1
    mock_client.return_value.chat.completions.create.return_value = resp
    mc = {"provider": "fireworks", "model": "m", "max_tokens": 100,
          "_obs": {"stage": "seams", "capture_dir": str(tmp_path)}}
    call_llm("SYSTEM-XYZ", "USER-ABC", mc, stream=False)
    call_llm("SYSTEM-2", "USER-2", mc, stream=False)  # second call → per-stage seq 02
    files = sorted(p.name for p in tmp_path.glob("seams__*.txt"))
    assert files == ["seams__01.txt", "seams__02.txt"]   # per-stage counter, not global
    content = (tmp_path / "seams__01.txt").read_text()
    assert "SYSTEM-XYZ" in content and "USER-ABC" in content
