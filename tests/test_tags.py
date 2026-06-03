"""Tests for morning_digest.tags — single source of truth for tag vocabulary."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_tag_labels_single_source_and_desk_tag_sets():
    from morning_digest.tags import TAG_LABELS, desk_tag_set, label_for_tag

    assert TAG_LABELS["war"] == "Conflict"
    assert label_for_tag("ai") == "AI"
    assert label_for_tag("not-a-tag") == "Not-A-Tag"  # safe titlecase fallback
    # Desk -> allowed tag set, derived from analyze_domain _DOMAIN_CONFIGS.
    assert desk_tag_set("ai_tech") == {"ai", "tech", "cyber"}
    assert desk_tag_set("econ") == {"econ"}
    assert desk_tag_set("unknown_desk") == set()
