"""HTTP client for article body fetches."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from typing import Optional

from curl_cffi import requests as curl_requests

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    status: str
    http_status: Optional[int]
    html: str
    error: str


def load_cookies_file(path: Optional[str]) -> Optional[MozillaCookieJar]:
    """Load a Netscape cookies.txt file, returning None on failure."""
    if not path:
        return None
    try:
        jar = MozillaCookieJar(path)
        jar.load(ignore_discard=True, ignore_expires=True)
        return jar
    except FileNotFoundError:
        log.warning(f"Cookies file not found: {path}")
    except Exception as exc:
        log.warning(f"Failed to load cookies file {path}: {exc}")
    return None


def _session_get(url: str, **kwargs):
    """Indirection seam for tests."""
    return curl_requests.get(url, **kwargs)


def fetch_article_html(
    url: str,
    impersonate: str = "chrome",
    timeout: int = 15,
    cookies: Optional[MozillaCookieJar] = None,
    user_agent: Optional[str] = None,
) -> FetchResult:
    """Fetch HTML from a URL. Never raises."""
    headers = {"User-Agent": user_agent} if user_agent else None
    try:
        response = _session_get(
            url,
            impersonate=impersonate,
            timeout=timeout,
            cookies=cookies,
            headers=headers,
            allow_redirects=True,
        )
    except Exception as exc:
        return FetchResult("http_error", None, "", str(exc))

    if 200 <= response.status_code < 300:
        return FetchResult("ok", response.status_code, response.text, "")
    return FetchResult(
        "http_error", response.status_code, "", f"HTTP {response.status_code}"
    )
