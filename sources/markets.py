"""Fetch market data. Uses Yahoo Finance public endpoints (no key required)."""

import logging
import requests

log = logging.getLogger(__name__)

YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"


def fetch_markets(config: dict) -> list[dict]:
    """Return current market data for configured symbols.
    
    Returns list of dicts: {label, price, change_pct, direction}
    """
    symbols_config = config.get("markets", {}).get("symbols", [])
    if not symbols_config:
        return []

    symbol_str = ",".join(s["symbol"] for s in symbols_config)
    label_map = {s["symbol"]: s["label"] for s in symbols_config}

    try:
        resp = requests.get(
            YAHOO_QUOTE_URL,
            params={"symbols": symbol_str},
            headers={"User-Agent": "MorningDigest/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        quotes = data.get("quoteResponse", {}).get("result", [])

        results = []
        for q in quotes:
            symbol = q.get("symbol", "")
            price = q.get("regularMarketPrice", 0)
            change = q.get("regularMarketChangePercent", 0)
            
            # Format price based on type
            if price > 1000:
                price_str = f"{price:,.0f}"
            elif price > 10:
                price_str = f"${price:.2f}"
            else:
                price_str = f"${price:.2f}"

            results.append({
                "label": label_map.get(symbol, symbol),
                "symbol": symbol,
                "price": price_str,
                "change_pct": round(change, 2),
                "direction": "up" if change >= 0 else "down",
            })

        return results

    except Exception as e:
        log.warning(f"Markets fetch failed: {e}. Trying fallback.")
        return _fallback_markets(config)


def _fallback_markets(config: dict) -> list[dict]:
    """If Yahoo Finance is blocked or rate-limited, return empty with a note."""
    # Could add Alpha Vantage fallback here using ALPHA_VANTAGE_KEY env var
    log.warning("Market data unavailable — will be omitted from digest")
    return []
