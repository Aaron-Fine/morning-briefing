"""Tests for the three new analysis desks: energy_materials, culture_structural, science_biotech."""

import sys
import os
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.analyze_domain import (
    _filter_rss,
    _empty_domain_result,
    _run_domain_pass,
    _DOMAIN_CONFIGS,
)


# ---------------------------------------------------------------------------
# Desk configuration tests
# ---------------------------------------------------------------------------


class TestNewDeskConfigs:
    """Verify the three new desk configs are well-formed and consistent."""

    NEW_DESKS = ["energy_materials", "culture_structural", "science_biotech"]

    def test_all_new_desks_present_in_domain_configs(self):
        for desk in self.NEW_DESKS:
            assert desk in _DOMAIN_CONFIGS, f"Missing desk: {desk}"

    def test_desk_configs_have_required_keys(self):
        required = {
            "label", "categories", "transcript_channels",
            "tags", "tag_labels", "normal_items", "max_items",
            "min_items", "domain_instructions",
        }
        for desk in self.NEW_DESKS:
            cfg = _DOMAIN_CONFIGS[desk]
            missing = required - set(cfg.keys())
            assert not missing, f"Desk '{desk}' missing keys: {missing}"

    def test_categories_are_sets(self):
        for desk in self.NEW_DESKS:
            assert isinstance(_DOMAIN_CONFIGS[desk]["categories"], set)

    def test_categories_match_expected_rss_categories(self):
        expected = {
            "energy_materials": {"energy-materials"},
            "culture_structural": {"culture-structural"},
            "science_biotech": {"science-biotech"},
        }
        for desk, cats in expected.items():
            assert _DOMAIN_CONFIGS[desk]["categories"] == cats

    def test_item_counts_are_reasonable(self):
        for desk in self.NEW_DESKS:
            cfg = _DOMAIN_CONFIGS[desk]
            assert cfg["min_items"] >= 0
            assert cfg["normal_items"] >= cfg["min_items"]
            assert cfg["max_items"] >= cfg["normal_items"]

    def test_culture_structural_allows_zero_items(self):
        """culture_structural has min_items=0 per scoping discipline."""
        assert _DOMAIN_CONFIGS["culture_structural"]["min_items"] == 0

    def test_domain_instructions_are_nonempty_strings(self):
        for desk in self.NEW_DESKS:
            instr = _DOMAIN_CONFIGS[desk]["domain_instructions"]
            assert isinstance(instr, str) and len(instr) > 100


# ---------------------------------------------------------------------------
# Source filtering tests
# ---------------------------------------------------------------------------


class TestNewDeskSourceFiltering:
    """Verify source filtering routes feeds to the correct desks."""

    def _make_rss(self, categories):
        return [
            {"category": cat, "source": f"Source-{cat}", "title": f"Art-{cat}",
             "url": f"https://example.com/{cat}", "summary": "S"}
            for cat in categories
        ]

    def test_energy_materials_filters_correctly(self):
        items = self._make_rss(["energy-materials", "econ-trade", "ai-tech"])
        result = _filter_rss(items, _DOMAIN_CONFIGS["energy_materials"]["categories"])
        assert len(result) == 1
        assert result[0]["category"] == "energy-materials"

    def test_culture_structural_filters_correctly(self):
        items = self._make_rss(["culture-structural", "non-western"])
        result = _filter_rss(items, _DOMAIN_CONFIGS["culture_structural"]["categories"])
        assert len(result) == 1
        assert result[0]["category"] == "culture-structural"

    def test_science_biotech_filters_correctly(self):
        items = self._make_rss(["science-biotech", "defense-mil"])
        result = _filter_rss(items, _DOMAIN_CONFIGS["science_biotech"]["categories"])
        assert len(result) == 1
        assert result[0]["category"] == "science-biotech"


# ---------------------------------------------------------------------------
# Empty result tests
# ---------------------------------------------------------------------------


class TestNewDeskEmptyResults:
    def test_energy_materials_empty_result(self):
        result = _empty_domain_result("energy_materials")
        assert result == {"items": []}

    def test_culture_structural_empty_result(self):
        result = _empty_domain_result("culture_structural")
        assert result == {"items": []}

    def test_science_biotech_empty_result(self):
        result = _empty_domain_result("science_biotech")
        assert result == {"items": []}


# ---------------------------------------------------------------------------
# Run domain pass tests (with mocked LLM)
# ---------------------------------------------------------------------------


class TestNewDeskRunPass:
    def _model_config(self):
        return {"provider": "fireworks"}

    def _make_rss(self, category):
        return [
            {"category": category, "source": "Test", "title": "Art",
             "url": "https://example.com/art", "summary": "Summary", "reliability": ""}
        ]

    @patch("stages.analyze_domain.call_llm")
    def test_energy_materials_pass_returns_items(self, mock_llm):
        mock_llm.return_value = {"items": [
            {"tag": "energy", "headline": "Grid strain", "facts": "F",
             "analysis": "A", "source_depth": "single-source",
             "connection_hooks": [], "links": [], "deep_dive_candidate": False,
             "deep_dive_rationale": None}
        ]}
        cfg = _DOMAIN_CONFIGS["energy_materials"]
        result = _run_domain_pass(
            "energy_materials", cfg, self._make_rss("energy-materials"),
            [], [], self._model_config()
        )
        assert len(result["items"]) == 1
        assert result["items"][0]["tag"] == "energy"

    @patch("stages.analyze_domain.call_llm")
    def test_culture_structural_pass_returns_items(self, mock_llm):
        mock_llm.return_value = {"items": [
            {"tag": "domestic", "headline": "Trust shift", "facts": "F",
             "analysis": "A", "source_depth": "single-source",
             "connection_hooks": [], "links": [], "deep_dive_candidate": False,
             "deep_dive_rationale": None}
        ]}
        cfg = _DOMAIN_CONFIGS["culture_structural"]
        result = _run_domain_pass(
            "culture_structural", cfg, self._make_rss("culture-structural"),
            [], [], self._model_config()
        )
        assert len(result["items"]) == 1

    @patch("stages.analyze_domain.call_llm")
    def test_science_biotech_pass_returns_items(self, mock_llm):
        mock_llm.return_value = {"items": [
            {"tag": "biotech", "headline": "Gene therapy", "facts": "F",
             "analysis": "A", "source_depth": "single-source",
             "connection_hooks": [], "links": [], "deep_dive_candidate": False,
             "deep_dive_rationale": None}
        ]}
        cfg = _DOMAIN_CONFIGS["science_biotech"]
        result = _run_domain_pass(
            "science_biotech", cfg, self._make_rss("science-biotech"),
            [], [], self._model_config()
        )
        assert len(result["items"]) == 1
        assert result["items"][0]["tag"] == "biotech"

    def test_no_sources_returns_empty(self):
        for desk in ["energy_materials", "culture_structural", "science_biotech"]:
            cfg = _DOMAIN_CONFIGS[desk]
            result = _run_domain_pass(
                desk, cfg, [], [], [], self._model_config()
            )
            assert result == {"items": []}


# ---------------------------------------------------------------------------
# Total desk count
# ---------------------------------------------------------------------------


class TestDeskCount:
    def test_eight_desks_total(self):
        assert len(_DOMAIN_CONFIGS) == 8, (
            f"Expected 8 desks, got {len(_DOMAIN_CONFIGS)}: {list(_DOMAIN_CONFIGS.keys())}"
        )

    def test_no_category_overlap_between_desks(self):
        """Each RSS category should route to exactly one desk."""
        seen = {}
        for desk, cfg in _DOMAIN_CONFIGS.items():
            for cat in cfg["categories"]:
                assert cat not in seen, (
                    f"Category '{cat}' claimed by both '{seen[cat]}' and '{desk}'"
                )
                seen[cat] = desk
