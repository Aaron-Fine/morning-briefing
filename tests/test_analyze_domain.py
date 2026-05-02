"""Tests for stages/analyze_domain.py — source filtering and formatting helpers."""

import sys
import os
import logging
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.analyze_domain import (
    _collect_research_requests,
    _filter_rss,
    _filter_transcripts,
    _fmt_rss_items,
    _fmt_transcripts,
    _fmt_markets,
    _successful_research_by_domain,
    _empty_domain_result,
    _resolve_domain_configs,
    _run_domain_pass,
    run,
    _DOMAIN_CONFIGS,
)


class TestFilterRss:
    def test_filters_by_category(self):
        items = [
            {"category": "ai-tech", "title": "AI"},
            {"category": "defense-mil", "title": "Defense"},
            {"category": "econ-trade", "title": "Econ"},
        ]
        result = _filter_rss(items, {"ai-tech"})
        assert len(result) == 1
        assert result[0]["title"] == "AI"

    def test_multiple_categories(self):
        items = [
            {"category": "ai-tech", "title": "AI"},
            {"category": "cyber", "title": "Cyber"},
            {"category": "econ-trade", "title": "Econ"},
        ]
        result = _filter_rss(items, {"ai-tech", "cyber"})
        assert len(result) == 2

    def test_no_matching_items(self):
        items = [{"category": "econ-trade", "title": "Econ"}]
        result = _filter_rss(items, {"ai-tech"})
        assert result == []

    def test_empty_items(self):
        assert _filter_rss([], {"ai-tech"}) == []

    def test_missing_category_key(self):
        items = [{"title": "No category"}]
        result = _filter_rss(items, {"ai-tech"})
        assert result == []

    def test_headline_radar_items_do_not_feed_analysis(self):
        items = [
            {"category": "econ-trade", "title": "Title-only", "analysis_mode": "headline_radar"},
            {"category": "econ-trade", "title": "Full-text"},
        ]
        result = _filter_rss(items, {"econ-trade"})
        assert len(result) == 1
        assert result[0]["title"] == "Full-text"


class TestFilterTranscripts:
    def test_filters_by_channel(self):
        transcripts = [
            {"channel": "Beau of the Fifth Column", "title": "T1"},
            {"channel": "Perun", "title": "T2"},
            {"channel": "Other", "title": "T3"},
        ]
        result = _filter_transcripts(transcripts, {"Beau of the Fifth Column"})
        assert len(result) == 1
        assert result[0]["title"] == "T1"

    def test_empty_transcripts(self):
        assert _filter_transcripts([], {"Perun"}) == []

    def test_missing_channel_key(self):
        transcripts = [{"title": "No channel"}]
        result = _filter_transcripts(transcripts, {"Perun"})
        assert result == []


class TestFmtRssItems:
    def test_formats_single_item(self):
        items = [
            {
                "source": "Test Source",
                "title": "Test Title",
                "url": "https://example.com",
                "summary": "A summary",
                "published": "2026-04-10T12:00:00Z",
            }
        ]
        result = _fmt_rss_items(items)
        assert "SOURCE: Test Source" in result
        assert "TITLE: Test Title" in result
        assert "URL: https://example.com" in result
        assert "SUMMARY: A summary" in result

    def test_truncates_published_to_date(self):
        test_date = "2026-04-10"
        items = [
            {
                "source": "S",
                "title": "T",
                "url": "https://example.com",
                "summary": "Summary",
                "published": f"{test_date}T12:00:00Z",
            }
        ]
        result = _fmt_rss_items(items)
        assert test_date in result
        assert "12:00:00" not in result

    def test_includes_reliability_note(self):
        items = [
            {
                "source": "S",
                "title": "T",
                "url": "https://example.com",
                "summary": "Summary",
                "reliability": "low",
            }
        ]
        result = _fmt_rss_items(items)
        assert "[low]" in result

    def test_omits_reliability_when_missing(self):
        items = [
            {
                "source": "S",
                "title": "T",
                "url": "https://example.com",
                "summary": "Summary",
            }
        ]
        result = _fmt_rss_items(items)
        assert "[" not in result.split("\n")[0]

    def test_empty_items_returns_placeholder(self):
        assert _fmt_rss_items([]) == "(no items)"

    def test_multiple_items_separated(self):
        items = [
            {"source": "S1", "title": "T1", "url": "https://a.com", "summary": "A"},
            {"source": "S2", "title": "T2", "url": "https://b.com", "summary": "B"},
        ]
        result = _fmt_rss_items(items)
        assert "\n---\n" in result


class TestFmtTranscripts:
    def test_formats_single_transcript(self):
        transcripts = [{"channel": "Ch1", "title": "T1", "transcript": "Content"}]
        result = _fmt_transcripts(transcripts)
        assert "CHANNEL: Ch1 [analysis-opinion]" in result
        assert "TITLE: T1" in result
        assert "Content" in result

    def test_uses_compressed_transcript_if_present(self):
        transcripts = [
            {
                "channel": "Ch1",
                "title": "T1",
                "transcript": "Raw",
                "compressed_transcript": "Compressed",
            }
        ]
        result = _fmt_transcripts(transcripts)
        assert "Compressed" in result
        assert "Raw" not in result

    def test_empty_transcripts_returns_placeholder(self):
        assert _fmt_transcripts([]) == "(none)"

    def test_multiple_transcripts_separated(self):
        transcripts = [
            {"channel": "Ch1", "title": "T1", "transcript": "A"},
            {"channel": "Ch2", "title": "T2", "transcript": "B"},
        ]
        result = _fmt_transcripts(transcripts)
        assert "\n---\n" in result


class TestFmtMarkets:
    def test_formats_market_data(self):
        markets = [
            {"label": "SPY", "price": "500", "change_pct": 1.5},
            {"label": "DIA", "price": "400", "change_pct": -0.8},
        ]
        result = _fmt_markets(markets)
        assert "SPY: $500 (+1.5%)" in result
        assert "DIA: $400 (-0.8%)" in result

    def test_uses_symbol_if_label_missing(self):
        markets = [{"symbol": "AAPL", "price": "200", "change_pct": 0.0}]
        result = _fmt_markets(markets)
        assert "AAPL: $200 (+0.0%)" in result

    def test_none_change_pct_treated_as_zero(self):
        markets = [{"label": "X", "price": "100", "change_pct": None}]
        result = _fmt_markets(markets)
        assert "+0.0%" in result

    def test_empty_markets_returns_placeholder(self):
        assert _fmt_markets([]) == "(no market data)"


class TestEmptyDomainResult:
    def test_regular_domain_has_only_items(self):
        result = _empty_domain_result("geopolitics")
        assert result == {"items": []}

    def test_econ_domain_has_market_context(self):
        result = _empty_domain_result("econ")
        assert result == {"items": [], "market_context": ""}

    def test_defense_space_has_only_items(self):
        result = _empty_domain_result("defense_space")
        assert result == {"items": []}


class TestResolveDomainConfigs:
    def test_uses_config_manifest_categories(self):
        resolved = _resolve_domain_configs(
            {
                "desks": [
                    {"name": "geopolitics", "categories": ["custom-cat"]},
                    {"name": "econ", "categories": ["econ-trade"]},
                ]
            }
        )
        assert list(resolved.keys()) == ["geopolitics_events", "econ"]
        assert resolved["geopolitics_events"]["categories"] == {"custom-cat"}

    def test_falls_back_to_builtin_configs(self):
        resolved = _resolve_domain_configs({})
        assert resolved.keys() == _DOMAIN_CONFIGS.keys()


class TestRunDomainPass:
    def _make_model_config(self):
        return {"provider": "fireworks"}

    def _make_rss_items(self, categories=None):
        if categories is None:
            categories = ["ai-tech"]
        return [
            {
                "category": cat,
                "source": "Test",
                "title": f"Article for {cat}",
                "url": f"https://example.com/{cat}",
                "summary": "Summary",
                "reliability": "",
            }
            for cat in categories
        ]

    def test_empty_sources_returns_empty_result(self, caplog):
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        with caplog.at_level(logging.WARNING):
            result = _run_domain_pass(
                "ai_tech", cfg, [], [], [], self._make_model_config()
            )
        assert result == {"items": []}
        assert "no source items" in caplog.text

    def test_econ_pass_includes_market_context_in_empty_result(self):
        cfg = _DOMAIN_CONFIGS["econ"]
        result = _run_domain_pass("econ", cfg, [], [], [], self._make_model_config())
        assert result == {"items": [], "market_context": ""}

    @patch("stages.analyze_domain.call_llm")
    def test_llm_success_returns_parsed_result(self, mock_llm):
        mock_llm.return_value = {
            "items": [
                {
                    "tag": "ai",
                    "headline": "Test headline",
                    "facts": "Test facts",
                    "analysis": "Test analysis",
                    "source_depth": "single-source",
                    "connection_hooks": [],
                    "links": [],
                    "deep_dive_candidate": False,
                    "deep_dive_rationale": None,
                }
            ]
        }
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        result = _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            [],
            [],
            self._make_model_config(),
        )
        assert len(result["items"]) == 1
        assert result["items"][0]["headline"] == "Test headline"

    @patch("stages.analyze_domain.call_llm")
    def test_research_requests_preserved_on_first_pass(self, mock_llm):
        url = "https://example.com/ai-tech"
        mock_llm.return_value = {
            "items": [],
            "research_requests": [
                {
                    "url": url,
                    "claim": "Need fuller detail",
                    "reason": "RSS summary is thin",
                    "priority": "high",
                    "expected_use": "Decide whether to include",
                }
            ],
        }
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        result = _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            [],
            [],
            self._make_model_config(),
            allow_research_requests=True,
        )
        assert result["research_requests"][0]["url"] == url
        assert "research_requests" in mock_llm.call_args.args[0]

    @patch("stages.analyze_domain.call_llm")
    def test_research_results_included_on_second_pass(self, mock_llm):
        mock_llm.return_value = {"items": []}
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            [],
            [],
            self._make_model_config(),
            research_results=[
                {
                    "status": "ok",
                    "source": "Test",
                    "title": "Article for ai-tech",
                    "url": "https://example.com/ai-tech",
                    "claim": "Need fuller detail",
                    "summary": "Fetched article detail.",
                }
            ],
        )
        assert "REQUESTED ARTICLE FETCH RESULTS" in mock_llm.call_args.args[1]

    @patch("stages.analyze_domain.call_llm")
    def test_llm_exception_returns_empty_result(self, mock_llm, caplog):
        mock_llm.side_effect = Exception("API error")
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        with caplog.at_level(logging.ERROR):
            result = _run_domain_pass(
                "ai_tech",
                cfg,
                self._make_rss_items(),
                [],
                [],
                self._make_model_config(),
            )
        assert result == {"items": [], "_failed": True}
        assert "LLM call failed" in caplog.text

    @patch("stages.analyze_domain.call_llm")
    def test_list_result_wrapped_in_items(self, mock_llm):
        mock_llm.return_value = [
            {
                "tag": "ai",
                "headline": "Test",
                "facts": "F",
                "analysis": "A",
                "source_depth": "single-source",
                "connection_hooks": [],
                "links": [],
                "deep_dive_candidate": False,
            }
        ]
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        result = _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            [],
            [],
            self._make_model_config(),
        )
        assert "items" in result
        assert len(result["items"]) == 1

    @patch("stages.analyze_domain.call_llm")
    def test_non_dict_result_returns_empty_items(self, mock_llm):
        mock_llm.return_value = "not a dict"
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        result = _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            [],
            [],
            self._make_model_config(),
        )
        assert result["items"] == []
        assert result["_contract_issues"] == [
            {
                "path": "domain_analysis.ai_tech",
                "message": "domain result is not an object",
            }
        ]

    @patch("stages.analyze_domain.call_llm")
    def test_non_list_items_returns_empty_items_with_contract_issue(self, mock_llm):
        mock_llm.return_value = {"items": {"headline": "wrong container"}}
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        result = _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            [],
            [],
            self._make_model_config(),
        )
        assert result["items"] == []
        assert result["_contract_issues"] == [
            {
                "path": "domain_analysis.ai_tech.items",
                "message": "items is not a list",
            }
        ]

    @patch("stages.analyze_domain.call_llm")
    def test_malformed_nested_structures_are_normalized(self, mock_llm):
        mock_llm.return_value = {
            "items": [
                {
                    "tag": "ai",
                    "headline": "Test",
                    "facts": "F",
                    "analysis": "A",
                    "source_depth": "single-source",
                    "connection_hooks": {"entity": "OpenAI"},
                    "links": "https://example.com/ai-tech",
                    "deep_dive_candidate": "yes",
                    "custom_field": "preserved",
                },
                "not an item",
            ]
        }
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        result = _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            [],
            [],
            self._make_model_config(),
        )

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["connection_hooks"] == []
        assert item["links"] == []
        assert item["deep_dive_candidate"] is True
        assert item["custom_field"] == "preserved"
        assert result["_contract_issues"] == [
            {
                "path": "domain_analysis.ai_tech.items[0].links",
                "message": "links is not a list",
            },
            {
                "path": "domain_analysis.ai_tech.items[0].connection_hooks",
                "message": "connection_hooks is not a list",
            },
            {
                "path": "domain_analysis.ai_tech.items[1]",
                "message": "domain item is not an object",
            },
        ]

    @patch("stages.analyze_domain.call_llm")
    def test_url_validation_strips_unknown_domains(self, mock_llm):
        mock_llm.return_value = {
            "items": [
                {
                    "tag": "ai",
                    "headline": "Test",
                    "facts": "F",
                    "analysis": "A",
                    "source_depth": "single-source",
                    "connection_hooks": [],
                    "links": [
                        {"url": "https://example.com/known"},
                        {"url": "https://hallucinated.com/fake"},
                    ],
                    "deep_dive_candidate": False,
                }
            ]
        }
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        result = _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            [],
            [],
            self._make_model_config(),
        )
        links = result["items"][0]["links"]
        assert len(links) == 1
        assert links[0]["url"] == "https://example.com/known"

    @patch("stages.analyze_domain.call_llm")
    def test_econ_pass_includes_market_data(self, mock_llm):
        mock_llm.return_value = {"items": [], "market_context": "Markets up."}
        cfg = _DOMAIN_CONFIGS["econ"]
        markets = [{"label": "SPY", "price": "500", "change_pct": 1.0}]
        result = _run_domain_pass(
            "econ",
            cfg,
            self._make_rss_items(["econ-trade"]),
            [],
            markets,
            self._make_model_config(),
        )
        assert result["market_context"] == "Markets up."

    @patch("stages.analyze_domain.call_llm")
    def test_econ_missing_market_context_adds_empty_string(self, mock_llm):
        mock_llm.return_value = {"items": []}
        cfg = _DOMAIN_CONFIGS["econ"]
        result = _run_domain_pass(
            "econ",
            cfg,
            self._make_rss_items(["econ-trade"]),
            [],
            [],
            self._make_model_config(),
        )
        assert result["market_context"] == ""

    @patch("stages.analyze_domain.call_llm")
    def test_passes_transcripts_to_prompt(self, mock_llm):
        mock_llm.return_value = {"items": []}
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        transcripts = [
            {"channel": "Theo - t3.gg", "title": "T1", "transcript": "Content"}
        ]
        _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            transcripts,
            [],
            self._make_model_config(),
        )
        call_args = mock_llm.call_args
        user_content = call_args[0][1]
        assert "Theo - t3.gg" in user_content
        assert "Content" in user_content

    @patch("stages.analyze_domain.call_llm")
    def test_passes_json_mode_and_stream(self, mock_llm):
        mock_llm.return_value = {"items": []}
        cfg = _DOMAIN_CONFIGS["ai_tech"]
        _run_domain_pass(
            "ai_tech",
            cfg,
            self._make_rss_items(),
            [],
            [],
            self._make_model_config(),
        )
        assert mock_llm.call_args[1]["json_mode"] is True
        assert mock_llm.call_args[1]["stream"] is True


class TestAnalyzeDomainFailures:
    @patch("stages.analyze_domain._run_all_domains")
    @patch("stages.analyze_domain._run_domain_pass")
    def test_failed_domains_are_reported_without_domain_retry(
        self, mock_run_domain_pass, mock_run_all_domains
    ):
        mock_run_all_domains.return_value = {
            "ai_tech": {"items": [], "_failed": True},
            "econ": {"items": [], "market_context": ""},
        }

        result = run(
            {"raw_sources": {"rss": [], "markets": []}, "compressed_transcripts": []},
            {"llm": {}},
            model_config={"provider": "fireworks"},
        )

        mock_run_domain_pass.assert_not_called()
        assert result["domain_analysis_failures"] == ["ai_tech"]

    @patch("stages.analyze_domain._run_all_domains")
    def test_contract_issues_are_returned_as_sidecar(self, mock_run_all_domains):
        mock_run_all_domains.return_value = {
            "ai_tech": {
                "items": [],
                "_contract_issues": [
                    {
                        "path": "domain_analysis.ai_tech.items",
                        "message": "items is not a list",
                    }
                ],
            }
        }

        result = run(
            {"raw_sources": {"rss": [], "markets": []}, "compressed_transcripts": []},
            {"llm": {}},
            model_config={"provider": "fireworks"},
        )

        assert result["domain_analysis"] == {"ai_tech": {"items": []}}
        assert result["domain_analysis_contract_issues"] == [
            {
                "domain": "ai_tech",
                "path": "domain_analysis.ai_tech.items",
                "message": "items is not a list",
            }
        ]


class TestDomainResearch:
    def test_collect_research_requests_accepts_known_urls_and_rejects_radar(self):
        rss_items = [
            {
                "category": "ai-tech",
                "source": "Open",
                "title": "Open article",
                "url": "https://example.com/open",
            },
            {
                "category": "ai-tech",
                "source": "Radar",
                "title": "Radar article",
                "url": "https://example.com/radar",
                "analysis_mode": "headline_radar",
            },
        ]
        domain_analysis = {
            "ai_tech": {
                "items": [],
                "research_requests": [
                    {
                        "url": "https://example.com/open",
                        "claim": "Open claim",
                        "reason": "thin",
                        "priority": "high",
                    },
                    {
                        "url": "https://example.com/radar",
                        "claim": "Radar claim",
                        "reason": "title only",
                    },
                ],
            }
        }

        requests = _collect_research_requests(
            domain_analysis,
            {"ai_tech": _DOMAIN_CONFIGS["ai_tech"]},
            rss_items,
            {"max_requests_per_desk": 2, "max_requests_total": 10},
        )

        assert requests[0]["status"] == "selected"
        assert requests[0]["source"] == "Open"
        assert requests[1]["status"] == "rejected_unknown_url"
        assert "research_requests" not in domain_analysis["ai_tech"]

    def test_collect_research_requests_enforces_caps(self):
        rss_items = [
            {
                "category": "ai-tech",
                "source": "Open",
                "title": f"Article {idx}",
                "url": f"https://example.com/{idx}",
            }
            for idx in range(3)
        ]
        domain_analysis = {
            "ai_tech": {
                "items": [],
                "research_requests": [
                    {"url": item["url"], "claim": "claim", "reason": "thin"}
                    for item in rss_items
                ],
            }
        }

        requests = _collect_research_requests(
            domain_analysis,
            {"ai_tech": _DOMAIN_CONFIGS["ai_tech"]},
            rss_items,
            {"max_requests_per_desk": 1, "max_requests_total": 10},
        )

        assert [request["status"] for request in requests] == [
            "selected",
            "rejected_per_desk_cap",
            "rejected_per_desk_cap",
        ]

    def test_successful_research_grouping_filters_failures(self):
        grouped = _successful_research_by_domain(
            {
                "results": [
                    {"domain": "ai_tech", "status": "ok", "summary": "Useful"},
                    {"domain": "ai_tech", "status": "http_error", "summary": ""},
                    {"domain": "econ", "status": "cache_hit:ok", "summary": "Cached"},
                ]
            }
        )

        assert [item["summary"] for item in grouped["ai_tech"]] == ["Useful"]
        assert [item["summary"] for item in grouped["econ"]] == ["Cached"]


class TestCategoryRebalance:
    def test_prepends_item_for_missing_category(self):
        from stages.analyze_domain import _rebalance_categories

        desk_result = {"items": [{"item_id": "x", "category": "non-western"}]}
        desk_cfg = {"categories": {"non-western", "western-analysis"}}
        rss_items = [
            {"category": "non-western", "title": "A", "url": "https://a.com", "source": "A"},
            {"category": "western-analysis", "title": "B", "url": "https://b.com", "source": "B"},
        ]
        result, log = _rebalance_categories("geopolitics", desk_result, desk_cfg, rss_items, [])
        assert len(result["items"]) == 2
        assert result["items"][0]["item_id"] == "geopolitics-western-analysis-rebalanced"
        assert len(log) == 1

    def test_noop_when_all_categories_represented(self):
        from stages.analyze_domain import _rebalance_categories

        desk_result = {
            "items": [
                {"item_id": "x", "category": "non-western"},
                {"item_id": "y", "category": "western-analysis"},
            ]
        }
        desk_cfg = {"categories": {"non-western", "western-analysis"}}
        rss_items = [
            {"category": "non-western", "title": "A", "url": "https://a.com"},
            {"category": "western-analysis", "title": "B", "url": "https://b.com"},
        ]
        result, log = _rebalance_categories("geopolitics", desk_result, desk_cfg, rss_items, [])
        assert len(result["items"]) == 2
        assert len(log) == 0

    def test_can_disable_rebalance_per_desk(self):
        from stages.analyze_domain import _rebalance_categories

        desk_result = {"items": [{"item_id": "x", "category": "non-western"}]}
        desk_cfg = {
            "categories": {"non-western", "western-analysis"},
            "category_rebalance": {"enabled": False},
        }
        rss_items = [
            {"category": "western-analysis", "title": "B", "url": "https://b.com", "source": "B"},
        ]
        result, log = _rebalance_categories("geopolitics", desk_result, desk_cfg, rss_items, [])
        assert result["items"] == [{"item_id": "x", "category": "non-western"}]
        assert log == []

    def test_category_share_cap_drops_excess_dominant_items(self):
        from stages.analyze_domain import _rebalance_categories

        desk_result = {
            "items": [
                {"item_id": "a", "category": "non-western"},
                {"item_id": "b", "category": "non-western"},
                {"item_id": "c", "category": "non-western"},
                {"item_id": "d", "category": "western-analysis"},
            ]
        }
        desk_cfg = {
            "categories": {"non-western", "western-analysis"},
            "category_rebalance": {"enabled": True, "max_category_share": 0.5},
        }
        result, log = _rebalance_categories("geopolitics", desk_result, desk_cfg, [], [])
        assert [item["item_id"] for item in result["items"]] == ["a", "b", "d"]
        assert any(entry["action"] == "dropped_for_category_share_cap" for entry in log)


class TestPerspectiveDesk:
    def test_perspective_in_domain_configs(self):
        assert "perspective" in _DOMAIN_CONFIGS
        cfg = _DOMAIN_CONFIGS["perspective"]
        assert cfg["categories"] == {"substack-independent", "perspective-diversity"}
        assert cfg["min_items"] == 0

    def test_run_extracts_perspective_framing(self):
        with patch("stages.analyze_domain.call_llm") as mock_llm:
            mock_llm.return_value = {
                "items": [{"headline": "Test framing", "facts": "F", "analysis": "A"}]
            }
            context = {
                "raw_sources": {
                    "rss": [
                        {"category": "substack-independent", "title": "T", "url": "https://t.com", "source": "S"}
                    ]
                },
                "compressed_transcripts": [],
            }
            config = {"llm": {"provider": "fireworks"}, "desks": [{"name": "perspective", "categories": ["substack-independent"]}]}
            result = run(context, config)
            assert "perspective_framing" in result
            assert len(result["perspective_framing"]["items"]) == 1
            assert "domain_analysis" not in result["perspective_framing"]
            assert "domain_analysis" in result
