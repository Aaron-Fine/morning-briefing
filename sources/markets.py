"""Fetch market data via Finnhub API."""

import os
import logging
import requests

log = logging.getLogger(__name__)

FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


def _get_api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY", "")
    if not key:
        raise ValueError("FINNHUB_API_KEY environment variable not set")
    return key


def fetch_markets(config: dict) -> list[dict]:
    """Return current market data for configured symbols.

    Returns list of dicts: {label, symbol, price, change_pct, direction}
    """
    symbols_config = config.get("markets", {}).get("symbols", [])
    if not symbols_config:
        return []

    try:
        api_key = _get_api_key()
    except ValueError as e:
        log.warning(f"Markets disabled: {e}")
        return []

    results = []
    consecutive_failures = 0
    for s in symbols_config:
        symbol = s["symbol"]
        # Back off if multiple symbols fail in a row (API may be down)
        if consecutive_failures >= 3:
            log.warning(f"Markets: {consecutive_failures} consecutive failures, skipping remaining symbols")
            break
        try:
            resp = requests.get(
                FINNHUB_QUOTE_URL,
                params={"symbol": symbol, "token": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            q = resp.json()

            price = q.get("c", 0)
            change = q.get("dp", 0)  # percent change

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
        except requests.exceptions.Timeout:
            log.warning(f"Quote fetch timed out for {symbol}")
            consecutive_failures += 1
        except requests.exceptions.ConnectionError:
            log.warning(f"Quote fetch connection error for {symbol}")
            consecutive_failures += 1
        except Exception as e:
            log.warning(f"Quote fetch failed for {symbol}: {e}")
            consecutive_failures += 1

    return results
