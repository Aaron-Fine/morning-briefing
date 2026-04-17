"""Tests for sources/markets.py."""

import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.markets import fetch_markets


class TestFetchMarkets:
    def test_empty_symbols_config(self):
        config = {"markets": {"symbols": []}}
        result = fetch_markets(config)
        assert result == []

    def test_no_markets_config(self):
        config = {}
        result = fetch_markets(config)
        assert result == []

    @patch.dict(os.environ, {}, clear=True)
    def test_returns_empty_without_api_key(self):
        config = {"markets": {"symbols": [{"symbol": "^GSPC", "label": "S&P 500"}]}}
        result = fetch_markets(config)
        assert result == []

    @patch("sources.markets.http_get_json")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_successful_quote(self, mock_get):
        mock_get.return_value = {"c": 5000.50, "dp": 1.25}

        config = {"markets": {"symbols": [{"symbol": "^GSPC", "label": "S&P 500"}]}}
        result = fetch_markets(config)
        assert len(result) == 1
        assert result[0]["label"] == "S&P 500"
        assert result[0]["symbol"] == "^GSPC"
        assert result[0]["price"] == "5,000"
        assert result[0]["change_pct"] == 1.25
        assert result[0]["direction"] == "up"

    @patch("sources.markets.http_get_json")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_negative_change_direction(self, mock_get):
        mock_get.return_value = {"c": 4900.00, "dp": -0.75}

        config = {"markets": {"symbols": [{"symbol": "^GSPC", "label": "S&P 500"}]}}
        result = fetch_markets(config)
        assert result[0]["direction"] == "down"
        assert result[0]["change_pct"] == -0.75

    @patch("sources.markets.http_get_json")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_high_price_formatting(self, mock_get):
        mock_get.return_value = {"c": 15000.00, "dp": 0.5}

        config = {"markets": {"symbols": [{"symbol": "^DJI", "label": "Dow Jones"}]}}
        result = fetch_markets(config)
        assert result[0]["price"] == "15,000"

    @patch("sources.markets.http_get_json")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_low_price_formatting(self, mock_get):
        mock_get.return_value = {"c": 150.50, "dp": 0.5}

        config = {"markets": {"symbols": [{"symbol": "AAPL", "label": "Apple"}]}}
        result = fetch_markets(config)
        assert result[0]["price"] == "$150.50"

    @patch("sources.markets.http_get_json")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_handles_fetch_failure(self, mock_get):
        # http_get_json returns None on any error (timeout, connection, HTTP).
        mock_get.return_value = None

        config = {"markets": {"symbols": [{"symbol": "^GSPC", "label": "S&P 500"}]}}
        result = fetch_markets(config)
        assert result == []

    @patch("sources.markets.http_get_json")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_circuit_breaker_after_3_failures(self, mock_get):
        mock_get.return_value = None

        config = {
            "markets": {
                "symbols": [
                    {"symbol": "A", "label": "A"},
                    {"symbol": "B", "label": "B"},
                    {"symbol": "C", "label": "C"},
                    {"symbol": "D", "label": "D"},
                    {"symbol": "E", "label": "E"},
                ]
            }
        }
        result = fetch_markets(config)
        assert result == []
        # Should have made exactly 3 requests before circuit breaker trips
        assert mock_get.call_count == 3

    @patch("sources.markets.http_get_json")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_multiple_symbols(self, mock_get):
        def _response(*args, **kwargs):
            symbol = kwargs.get("params", {}).get("symbol", "")
            if symbol == "^GSPC":
                return {"c": 5000.00, "dp": 1.0}
            if symbol == "AAPL":
                return {"c": 180.00, "dp": -0.5}
            return None

        mock_get.side_effect = _response

        config = {
            "markets": {
                "symbols": [
                    {"symbol": "^GSPC", "label": "S&P 500"},
                    {"symbol": "AAPL", "label": "Apple"},
                ]
            }
        }
        result = fetch_markets(config)
        assert len(result) == 2
        assert result[0]["symbol"] == "^GSPC"
        assert result[1]["symbol"] == "AAPL"
