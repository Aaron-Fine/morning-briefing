"""Pure metric aggregation helpers. No I/O, no global state."""
from __future__ import annotations

from collections import Counter

from morning_digest.llm import LLMUsage


def aggregate_usage(records: list[LLMUsage]) -> dict:
    if not records:
        return {"model": None, "tokens_in": 0, "tokens_out": 0,
                "tokens_cached": 0, "usage_missing": 0}
    tokens_in = sum(r.tokens_in or 0 for r in records)
    tokens_out = sum(r.tokens_out or 0 for r in records)
    tokens_cached = sum(r.tokens_cached or 0 for r in records)
    missing = sum(1 for r in records if r.tokens_in is None or r.tokens_out is None)
    dominant = Counter(r.model for r in records).most_common(1)[0][0]
    return {
        "model": dominant,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_cached": tokens_cached,
        "usage_missing": missing,
    }
