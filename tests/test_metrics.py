from morning_digest.metrics import aggregate_usage
from morning_digest.llm import LLMUsage


def test_aggregate_usage_sums_and_counts_missing():
    records = [
        LLMUsage("m1", "fireworks", 100, 40, 30),
        LLMUsage("m1", "fireworks", 50, 10, 0),
        LLMUsage("m2", "fireworks", None, None, None),
    ]
    agg = aggregate_usage(records)
    assert agg["tokens_in"] == 150
    assert agg["tokens_out"] == 50
    assert agg["tokens_cached"] == 30
    assert agg["usage_missing"] == 1
    assert agg["model"] == "m1"  # dominant by call count


def test_aggregate_usage_empty():
    agg = aggregate_usage([])
    assert agg == {"model": None, "tokens_in": 0, "tokens_out": 0,
                   "tokens_cached": 0, "usage_missing": 0}
