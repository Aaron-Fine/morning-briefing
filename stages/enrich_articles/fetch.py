"""Fetch state machine for article enrichment.

`resolve_source_text` collapses the cascading HTTP / browser fetch attempts
into a single linear pipeline that returns one `FetchAttempt` describing
what the caller should use (or cache and bail on).
"""

from __future__ import annotations

from dataclasses import dataclass

from sources.article_browser_fetch import fetch_article_browser_markdown
from sources.article_extract import extract_article
from sources.article_fetch import fetch_article_html, load_cookies_file

from .scheduling import _HostLimiter


@dataclass
class FetchAttempt:
    """Outcome of resolving source text for a single article.

    - `success=True, terminal=False`: use `text`/`origin` as the source_text;
      any `error` is advisory and should be annotated onto the final record.
    - `success=False, terminal=True`: fetch failed definitively; caller should
      cache a failure entry and return without summarizing.
    - `success=False, terminal=False`: no fetch attempted / not usable, but not
      terminal (e.g. native_text was empty and no fetches allowed — caller will
      produce a `no_source_text` record).
    """

    text: str = ""
    origin: str = ""
    status: str = "ok"
    error: str = ""
    http_status: int | None = None
    fetched_length: int = 0
    success: bool = False
    terminal: bool = False


def _fetch_source_text(
    url: str,
    feed_conf: dict,
    enrich_cfg: dict,
    limiter: _HostLimiter,
) -> tuple[str, str, int | None, int, str]:
    per_feed = (feed_conf or {}).get("enrich", {}) or {}
    cookies_path = per_feed.get("cookies_file")
    cookies = load_cookies_file(cookies_path) if cookies_path else None
    impersonate = per_feed.get("impersonate") or enrich_cfg.get("impersonate", "chrome")
    timeout = int(per_feed.get("timeout_seconds") or enrich_cfg.get("timeout_seconds", 15))
    user_agent = per_feed.get("user_agent") or enrich_cfg.get("user_agent")
    min_body_chars = int(per_feed.get("min_body_chars") or enrich_cfg.get("min_body_chars", 300))

    fetched = limiter.run(
        url,
        lambda: fetch_article_html(
            url,
            impersonate=impersonate,
            timeout=timeout,
            cookies=cookies,
            user_agent=user_agent,
        ),
    )
    if fetched.status != "ok":
        return "", fetched.status, fetched.http_status, 0, fetched.error

    extracted = extract_article(fetched.html, min_body_chars=min_body_chars)
    if extracted.status != "ok":
        return "", extracted.status, fetched.http_status, extracted.raw_length, ""
    return extracted.text, "ok", fetched.http_status, extracted.raw_length, ""


def _fetch_browser_source_text(
    url: str,
    feed_conf: dict,
    enrich_cfg: dict,
    limiter: _HostLimiter,
) -> tuple[str, str, int | None, int, str]:
    fetched = limiter.run(
        url,
        lambda: fetch_article_browser_markdown(url, feed_conf, enrich_cfg),
    )
    if fetched.status != "ok":
        return "", fetched.status, fetched.http_status, fetched.raw_length, fetched.error
    min_body_chars = int(
        ((feed_conf or {}).get("enrich", {}) or {}).get("min_body_chars")
        or enrich_cfg.get("min_body_chars", 300)
    )
    if fetched.raw_length < min_body_chars:
        return (
            "",
            "extraction_failed",
            fetched.http_status,
            fetched.raw_length,
            "browser markdown shorter than min_body_chars",
        )
    return fetched.markdown, "ok", fetched.http_status, fetched.raw_length, ""


def _join_errors(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


def _has_usable_native(native_text: str, native_origin: str) -> bool:
    return bool(native_text) and native_origin in {"rss_body", "content", "content_encoded"}


def resolve_source_text(
    url: str,
    feed_conf: dict,
    strategy: str,
    native_text: str,
    native_origin: str,
    http_fetch_allowed: bool,
    browser_fetch_allowed: bool,
    enrich_cfg: dict,
    limiter: _HostLimiter,
) -> FetchAttempt:
    """Linear fetch state machine: native → browser (if strategy) → HTTP → browser fallback."""
    attempt = FetchAttempt(
        text=native_text,
        origin=native_origin,
        success=bool(native_text),
    )

    if browser_fetch_allowed and strategy == "browser_fetch":
        b_text, b_status, b_http, b_len, b_err = _fetch_browser_source_text(
            url, feed_conf, enrich_cfg, limiter
        )
        if b_status == "ok":
            return FetchAttempt(
                text=b_text,
                origin="browser_markdown",
                status="ok",
                http_status=b_http,
                fetched_length=b_len,
                success=True,
            )
        if not native_text:
            return FetchAttempt(
                origin="browser_markdown",
                status=b_status,
                error=b_err,
                http_status=b_http,
                fetched_length=b_len,
                terminal=True,
            )
        attempt.error = f"browser {b_status}: {b_err}".strip()

    if http_fetch_allowed and attempt.origin != "browser_markdown":
        h_text, h_status, h_http, h_len, h_err = _fetch_source_text(
            url, feed_conf, enrich_cfg, limiter
        )
        if h_status == "ok":
            return FetchAttempt(
                text=h_text,
                origin="fetched_html",
                status="ok",
                http_status=h_http,
                fetched_length=h_len,
                error=attempt.error,
                success=True,
            )

        if browser_fetch_allowed:
            b_text, b_status, b_http, b_len, b_err = _fetch_browser_source_text(
                url, feed_conf, enrich_cfg, limiter
            )
            if b_status == "ok":
                return FetchAttempt(
                    text=b_text,
                    origin="browser_markdown",
                    status="ok",
                    http_status=b_http,
                    fetched_length=b_len,
                    error=f"fetch {h_status}: {h_err}".strip(),
                    success=True,
                )
            if _has_usable_native(native_text, native_origin):
                attempt.error = _join_errors(
                    f"fetch {h_status}: {h_err}".strip(),
                    f"browser {b_status}: {b_err}".strip(),
                )
                return attempt
            return FetchAttempt(
                origin="browser_markdown",
                status=b_status,
                error=b_err,
                http_status=b_http,
                fetched_length=b_len,
                terminal=True,
            )

        if _has_usable_native(native_text, native_origin):
            attempt.error = f"fetch {h_status}: {h_err}".strip()
            return attempt
        return FetchAttempt(
            origin="fetched_html",
            status=h_status,
            error=h_err,
            http_status=h_http,
            fetched_length=h_len,
            terminal=True,
        )

    return attempt
