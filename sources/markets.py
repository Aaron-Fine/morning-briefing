"""Fetch market data via Finnhub API."""

import os
import logging

from sources._http import http_get_json

log = logging.getLogger(__name__)

FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


def fetch_markets(config: dict) -> list[dict]:
    """Return current market data for configured symbols.

    Returns list of dicts: {label, symbol, price, change_pct, direction}
    """
    symbols_config = config.get("markets", {}).get("symbols", [])
    if not symbols_config:
        return []

    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        log.warning("Markets disabled: FINNHUB_API_KEY not set")
        return []

    results = []
    consecutive_failures = 0
    for s in symbols_config:
        symbol = s["symbol"]
        # Back off if multiple symbols fail in a row (API may be down)
        if consecutive_failures >= 3:
            log.warning(f"Markets: {consecutive_failures} consecutive failures, skipping remaining symbols")
            break

        q = http_get_json(
            FINNHUB_QUOTE_URL,
            params={"symbol": symbol, "token": api_key},
            timeout=10,
            label=f"Quote {symbol}",
        )
        if q is None:
            consecutive_failures += 1
            continue

        price = q.get("c", 0)
        change = q.get("dp", 0)

        is_index = symbol.startswith("^")
        if price > 1000:
            price_str = f"{price:,.0f}"
        elif is_index:
            price_str = f"{price:.2f}"
        else:
            price_str = f"${price:.2f}"

        results.append({
            "label": s["label"],
            "symbol": symbol,
            "price": price_str,
            "change_pct": round(change, 2),
            "direction": "up" if change >= 0 else "down",
        })
        consecutive_failures = 0

    return results
