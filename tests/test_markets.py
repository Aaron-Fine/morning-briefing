"""Tests for sources/markets.py."""

import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.markets import fetch_markets, _get_api_key


class TestGetApiKey:
    def test_returns_key_from_env(self):
        with patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key_123"}):
            assert _get_api_key() == "test_key_123"

    def test_raises_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError):
                _get_api_key()


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

    @patch("sources.markets.requests.get")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_successful_quote(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"c": 5000.50, "dp": 1.25}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        config = {"markets": {"symbols": [{"symbol": "^GSPC", "label": "S&P 500"}]}}
        result = fetch_markets(config)
        assert len(result) == 1
        assert result[0]["label"] == "S&P 500"
        assert result[0]["symbol"] == "^GSPC"
        assert result[0]["price"] == "5,000"
        assert result[0]["change_pct"] == 1.25
        assert result[0]["direction"] == "up"

    @patch("sources.markets.requests.get")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_negative_change_direction(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"c": 4900.00, "dp": -0.75}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        config = {"markets": {"symbols": [{"symbol": "^GSPC", "label": "S&P 500"}]}}
        result = fetch_markets(config)
        assert result[0]["direction"] == "down"
        assert result[0]["change_pct"] == -0.75

    @patch("sources.markets.requests.get")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_high_price_formatting(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"c": 15000.00, "dp": 0.5}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        config = {"markets": {"symbols": [{"symbol": "^DJI", "label": "Dow Jones"}]}}
        result = fetch_markets(config)
        assert result[0]["price"] == "15,000"

    @patch("sources.markets.requests.get")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_low_price_formatting(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"c": 150.50, "dp": 0.5}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        config = {"markets": {"symbols": [{"symbol": "AAPL", "label": "Apple"}]}}
        result = fetch_markets(config)
        assert result[0]["price"] == "$150.50"

    @patch("sources.markets.requests.get")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_handles_timeout(self, mock_get):
        import requests

        mock_get.side_effect = requests.exceptions.Timeout()

        config = {"markets": {"symbols": [{"symbol": "^GSPC", "label": "S&P 500"}]}}
        result = fetch_markets(config)
        assert result == []

    @patch("sources.markets.requests.get")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_handles_connection_error(self, mock_get):
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError()

        config = {"markets": {"symbols": [{"symbol": "^GSPC", "label": "S&P 500"}]}}
        result = fetch_markets(config)
        assert result == []

    @patch("sources.markets.requests.get")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_circuit_breaker_after_3_failures(self, mock_get):
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError()

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
        # Should have made exactly 3 requests before circuit breaker
        assert mock_get.call_count == 3

    @patch("sources.markets.requests.get")
    @patch.dict(os.environ, {"FINNHUB_API_KEY": "test_key"})
    def test_multiple_symbols(self, mock_get):
        def mock_response(*args, **kwargs):
            symbol = kwargs.get("params", {}).get("symbol", "")
            mock_resp = MagicMock()
            if symbol == "^GSPC":
                mock_resp.json.return_value = {"c": 5000.00, "dp": 1.0}
            elif symbol == "AAPL":
                mock_resp.json.return_value = {"c": 180.00, "dp": -0.5}
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        mock_get.side_effect = mock_response

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
