"""Shared HTTP helper for source fetches.

Enforces a canonical User-Agent, default timeout, and uniform error logging
so individual sources don't each hand-roll the same try/except shape.

Each helper returns None on any error (timeout, connection, HTTP status,
parse); callers should treat None as "couldn't fetch" and return their
empty-result default.
"""

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

_DEFAULT_UA = "MorningDigest/1.0 (morningDigest@lurkers.us)"
_DEFAULT_TIMEOUT = 15


def _headers(extra: dict | None) -> dict:
    merged = {"User-Agent": _DEFAULT_UA}
    if extra:
        merged.update(extra)
    return merged


def _get(
    url: str,
    *,
    params: dict | None,
    headers: dict | None,
    timeout: int,
    label: str,
) -> requests.Response | None:
    try:
        resp = requests.get(
            url, params=params, headers=_headers(headers), timeout=timeout
        )
        resp.raise_for_status()
        return resp
    except Exception as e:
        log.warning(f"{label or url}: HTTP GET failed: {e}")
        return None


def http_get_json(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    label: str = "",
) -> Any | None:
    """GET url and return parsed JSON, or None on any failure."""
    resp = _get(url, params=params, headers=headers, timeout=timeout, label=label)
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception as e:
        log.warning(f"{label or url}: JSON parse failed: {e}")
        return None


def http_get_text(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    label: str = "",
) -> str | None:
    """GET url and return response text, or None on any failure."""
    resp = _get(url, params=params, headers=headers, timeout=timeout, label=label)
    return resp.text if resp is not None else None


def http_get_bytes(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    label: str = "",
) -> bytes | None:
    """GET url and return response bytes, or None on any failure."""
    resp = _get(url, params=params, headers=headers, timeout=timeout, label=label)
    return resp.content if resp is not None else None
