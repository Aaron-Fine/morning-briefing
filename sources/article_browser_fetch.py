"""Browser-backed article extraction using Crawl4AI."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from typing import Any, Optional

from sources.article_fetch import load_cookies_file

log = logging.getLogger(__name__)
_BROWSER_FETCH_LOCK = threading.Lock()


@dataclass
class BrowserFetchResult:
    status: str
    markdown: str
    raw_length: int
    http_status: Optional[int]
    error: str


def fetch_article_browser_markdown(
    url: str,
    feed_conf: dict,
    enrich_cfg: dict,
) -> BrowserFetchResult:
    """Fetch rendered article markdown via Crawl4AI. Never raises."""
    with _BROWSER_FETCH_LOCK:
        return _fetch_article_browser_markdown_locked(url, feed_conf, enrich_cfg)


def _fetch_article_browser_markdown_locked(
    url: str,
    feed_conf: dict,
    enrich_cfg: dict,
) -> BrowserFetchResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(
                _fetch_article_browser_markdown_async(url, feed_conf, enrich_cfg)
            )
        except Exception as exc:
            return BrowserFetchResult("browser_failed", "", 0, None, str(exc))
    return BrowserFetchResult(
        "browser_failed",
        "",
        0,
        None,
        "browser fetch cannot run inside an active event loop",
    )


async def _fetch_article_browser_markdown_async(
    url: str,
    feed_conf: dict,
    enrich_cfg: dict,
) -> BrowserFetchResult:
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        from crawl4ai import CacheMode
    except Exception as exc:
        return BrowserFetchResult(
            "browser_unavailable",
            "",
            0,
            None,
            f"Crawl4AI unavailable: {exc}",
        )

    per_feed = (feed_conf or {}).get("enrich", {}) or {}
    cookies = _load_browser_cookies(per_feed.get("cookies_file"))
    timeout_seconds = int(
        per_feed.get("browser_timeout_seconds")
        or enrich_cfg.get("browser_timeout_seconds")
        or enrich_cfg.get("timeout_seconds", 30)
    )
    user_agent = per_feed.get("user_agent") or enrich_cfg.get("user_agent")

    browser_cfg = _construct(
        BrowserConfig,
        browser_type="chromium",
        headless=True,
        text_mode=True,
        light_mode=True,
        cookies=cookies or None,
        user_agent=user_agent,
        verbose=False,
    )
    run_cfg = _construct(
        CrawlerRunConfig,
        cache_mode=getattr(CacheMode, "BYPASS", None),
        wait_for=per_feed.get("browser_wait_for"),
        js_code=per_feed.get("browser_js") or None,
        page_timeout=timeout_seconds * 1000,
        remove_overlay_elements=True,
        remove_consent_popups=True,
        remove_forms=True,
        exclude_external_links=True,
        magic=bool(per_feed.get("browser_magic", enrich_cfg.get("browser_magic", False))),
        verbose=False,
        word_count_threshold=10,
    )

    try:
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)
    except Exception as exc:
        return BrowserFetchResult("browser_failed", "", 0, None, str(exc))

    markdown = _coerce_markdown(getattr(result, "markdown", ""))
    http_status = getattr(result, "status_code", None)
    success = getattr(result, "success", bool(markdown))
    if success and markdown.strip():
        cleaned = _clean_markdown(markdown)
        return BrowserFetchResult("ok", cleaned, len(cleaned), http_status, "")

    error = getattr(result, "error_message", "") or "empty browser markdown"
    return BrowserFetchResult("browser_failed", "", len(markdown or ""), http_status, error)


def _construct(cls, **kwargs):
    """Instantiate Crawl4AI config classes across minor API differences."""
    allowed = {
        key: value
        for key, value in kwargs.items()
        if value is not None and _accepts_kwarg(cls, key)
    }
    return cls(**allowed)


def _accepts_kwarg(cls, key: str) -> bool:
    try:
        signature = inspect.signature(cls)
    except (TypeError, ValueError):
        return True
    return key in signature.parameters


def _load_browser_cookies(path: Optional[str]) -> list[dict[str, Any]]:
    jar = load_cookies_file(path)
    if jar is None:
        return []
    return _cookies_to_browser_format(jar)


def _cookies_to_browser_format(jar: MozillaCookieJar) -> list[dict[str, Any]]:
    cookies = []
    for cookie in jar:
        data: dict[str, Any] = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path or "/",
            "secure": bool(cookie.secure),
            "httpOnly": bool(cookie.has_nonstandard_attr("HttpOnly")),
        }
        if cookie.expires:
            data["expires"] = cookie.expires
        cookies.append(data)
    return cookies


def _coerce_markdown(value: Any) -> str:
    if isinstance(value, str):
        return value
    for attr in ("raw_markdown", "fit_markdown", "markdown"):
        candidate = getattr(value, attr, None)
        if candidate:
            return str(candidate)
    return str(value or "")


def _clean_markdown(markdown: str) -> str:
    lines = []
    for line in markdown.splitlines():
        clean = " ".join(line.strip().split())
        if clean:
            lines.append(clean)
    return "\n".join(lines)
