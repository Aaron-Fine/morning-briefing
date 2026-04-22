"""Stage: enrich_articles — write enriched RSS items to a separate source artifact."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from morning_digest.llm import call_llm
from morning_digest.sanitize import sanitize_source_content
from sources.article_browser_fetch import fetch_article_browser_markdown
from sources.article_cache import ArticleCache
from sources.article_content import (
    best_native_text,
    needs_distillation,
    needs_fetch,
    resolve_strategy,
)
from sources.article_extract import extract_article
from sources.article_fetch import fetch_article_html, load_cookies_file
from utils.prompts import load_prompt

log = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path(__file__).parent.parent / "cache" / "article_bodies"
_MAX_PARALLEL = 4


@dataclass
class _HostState:
    semaphore: threading.Semaphore
    lock: threading.Lock
    last_fetch: float = 0.0


class _HostLimiter:
    def __init__(self, concurrency: int, min_interval_ms: int) -> None:
        self._concurrency = max(1, int(concurrency or 1))
        self._min_interval = max(0, int(min_interval_ms or 0)) / 1000
        self._states: dict[str, _HostState] = {}
        self._states_lock = threading.Lock()

    def _state_for(self, url: str) -> _HostState:
        host = urlparse(url).netloc or "unknown"
        with self._states_lock:
            if host not in self._states:
                self._states[host] = _HostState(
                    threading.Semaphore(self._concurrency),
                    threading.Lock(),
                )
            return self._states[host]

    def run(self, url: str, fn):
        state = self._state_for(url)
        with state.semaphore:
            with state.lock:
                elapsed = time.monotonic() - state.last_fetch
                if state.last_fetch and elapsed < self._min_interval:
                    time.sleep(self._min_interval - elapsed)
                state.last_fetch = time.monotonic()
            return fn()


@dataclass
class _Candidate:
    item: dict
    feed_conf: dict
    native_text: str
    strategy: str
    http_fetch_needed: bool
    browser_fetch_candidate: bool
    priority: tuple[int, int, int, int]
    priority_reason: str
    http_fetch_allowed: bool = False
    browser_fetch_allowed: bool = False


@dataclass
class _CanonicalResult:
    summary: str
    status: str
    error: str = ""
    fallback_reason: str = ""
    rejected_summary_preview: str = ""


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Normalize RSS item summaries from best available source text."""
    enriched_sources = deepcopy(context.get("raw_sources", {}))
    items = enriched_sources.get("rss", []) or []
    enrich_cfg = config.get("enrich_articles", {}) or {}

    if not enrich_cfg.get("enabled", True) or not items:
        return {
            "enriched_sources": enriched_sources,
            "enrich_articles": {"records": []},
        }

    cache = ArticleCache(
        Path(config.get("_test_cache_dir") or _DEFAULT_CACHE_DIR),
        ttl_days=enrich_cfg.get("cache_ttl_days", 30),
        failure_backoff_hours=enrich_cfg.get("cache_failure_backoff_hours", 24),
    )
    pruned = cache.prune()
    if pruned:
        log.info(f"enrich_articles: pruned {pruned} expired cache entries")

    feeds_by_name = {f.get("name"): f for f in config.get("rss", {}).get("feeds", [])}
    canonical_by_url, order = _dedup_by_url(items)

    max_fetches = int(enrich_cfg.get("max_fetches_per_run", 40))
    max_browser_fetches = int(enrich_cfg.get("max_browser_fetches_per_run", 0))
    browser_enabled = bool(enrich_cfg.get("browser_fetch_enabled", False))
    candidates = []
    skipped_records = []
    for url in order:
        item = canonical_by_url[url]
        feed_conf = feeds_by_name.get(item.get("source"), {})
        native_text, _origin = best_native_text(item)
        strategy = resolve_strategy(feed_conf)
        fetch_needed = needs_fetch(
            native_text,
            strategy,
            int(enrich_cfg.get("min_usable_chars", 200)),
        )
        browser_candidate = _browser_fetch_candidate(
            native_text,
            strategy,
            browser_enabled,
            int(enrich_cfg.get("min_usable_chars", 200)),
        )
        priority, reason = _candidate_priority(
            item,
            feed_conf,
            native_text,
            strategy,
            len(candidates),
        )
        candidates.append(
            _Candidate(
                item=item,
                feed_conf=feed_conf,
                native_text=native_text,
                strategy=strategy,
                http_fetch_needed=fetch_needed,
                browser_fetch_candidate=browser_candidate,
                priority=priority,
                priority_reason=reason,
            )
        )

    _allocate_budget(
        candidates,
        attr_needed="http_fetch_needed",
        attr_allowed="http_fetch_allowed",
        cap=max_fetches,
        skipped_status="skipped_fetch_cap",
        skipped_records=skipped_records,
    )
    _allocate_budget(
        candidates,
        attr_needed="browser_fetch_candidate",
        attr_allowed="browser_fetch_allowed",
        cap=max_browser_fetches,
        skipped_status="skipped_browser_fetch_cap",
        skipped_records=skipped_records,
    )
    jobs = sorted(candidates, key=lambda candidate: candidate.priority)

    limiter = _HostLimiter(
        enrich_cfg.get("per_host_concurrency", 2),
        enrich_cfg.get("per_host_min_interval_ms", 500),
    )
    system_prompt = load_prompt("enrich_article_system.md")
    status_records = list(skipped_records)

    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(jobs) or 1)) as pool:
        futures = {
            pool.submit(
                _normalize_one,
                candidate.item,
                candidate.feed_conf,
                candidate.http_fetch_allowed,
                candidate.browser_fetch_allowed,
                enrich_cfg,
                cache,
                limiter,
                system_prompt,
                model_config,
            ): candidate.item
            for candidate in jobs
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                status_records.append(future.result())
            except Exception as exc:
                log.error(f"enrich_articles: failed for {item.get('url')}: {exc}")
                status_records.append(_record(item, "exception", str(exc)))

    for item in items:
        canonical = canonical_by_url.get(item.get("url"))
        if canonical is not None and canonical is not item:
            item["summary"] = canonical.get("summary", item.get("summary", ""))

    enriched_sources["rss"] = items
    return {
        "enriched_sources": enriched_sources,
        "enrich_articles": {"records": status_records},
    }


def _dedup_by_url(items: list[dict]) -> tuple[dict[str, dict], list[str]]:
    canonical: dict[str, dict] = {}
    order: list[str] = []
    for item in items:
        url = item.get("url")
        if not url or url in canonical:
            continue
        canonical[url] = item
        order.append(url)
    return canonical, order


def _browser_fetch_candidate(
    native_text: str,
    strategy: str,
    browser_enabled: bool,
    min_usable_chars: int,
) -> bool:
    if not browser_enabled:
        return False
    if strategy == "browser_fetch":
        return True
    if strategy != "auto":
        return False
    return not native_text


def _candidate_priority(
    item: dict,
    feed_conf: dict,
    native_text: str,
    strategy: str,
    index: int,
) -> tuple[tuple[int, int, int, int], str]:
    if strategy == "skip":
        return (5, 1, len(native_text or ""), index), "skip"
    if not native_text:
        return (0, 0, 0, index), "empty_native_text"
    if strategy in {"fetch", "fetch_with_cookies", "browser_fetch"}:
        return (1, 0, len(native_text), index), f"explicit_{strategy}"
    priority = int((feed_conf or {}).get("priority", 5) or 5)
    if priority <= 2:
        return (2, priority, len(native_text), index), "high_priority_feed"
    return (3, priority, len(native_text), index), "short_native_text"


def _allocate_budget(
    candidates: list[_Candidate],
    *,
    attr_needed: str,
    attr_allowed: str,
    cap: int,
    skipped_status: str,
    skipped_records: list[dict],
) -> None:
    budget = max(0, int(cap or 0))
    needed = [candidate for candidate in candidates if getattr(candidate, attr_needed)]
    needed.sort(key=lambda candidate: candidate.priority)
    for idx, candidate in enumerate(needed):
        if idx < budget:
            setattr(candidate, attr_allowed, True)
            continue
        skipped_records.append(
            _record(
                candidate.item,
                skipped_status,
                f"{skipped_status.replace('_', ' ')} hit; rank_reason={candidate.priority_reason}; candidates={len(needed)}",
                source_text_origin="",
                native_length=len(candidate.native_text or ""),
            )
        )


def _normalize_one(
    item: dict,
    feed_conf: dict,
    http_fetch_allowed: bool,
    browser_fetch_allowed: bool,
    enrich_cfg: dict,
    cache: ArticleCache,
    limiter: _HostLimiter,
    system_prompt: str,
    model_config: dict | None,
) -> dict:
    original_summary = item.get("summary", "") or ""
    source = item.get("source", "")
    url = item.get("url", "")
    strategy = resolve_strategy(feed_conf)
    native_text, native_origin = best_native_text(item)
    native_length = len(native_text)

    if strategy == "skip":
        return _record(
            item,
            "skipped",
            "",
            source_text_origin=native_origin,
            native_length=native_length,
        )

    cached = cache.get(url)
    if cached is not None:
        record = _record(
            item,
            f"cache_hit:{cached.status}",
            cached.error,
            source_text_origin=cached.source_text_origin,
            native_length=native_length,
            fetched_length=(
                cached.raw_length
                if cached.source_text_origin in {"fetched_html", "browser_markdown"}
                else 0
            ),
            summary_length=cached.summary_length,
            http_status=cached.http_status,
            fallback_reason=cached.fallback_reason,
            rejected_summary_preview=cached.rejected_summary_preview,
        )
        cached_summary_statuses = {"ok", "normalizer_fallback", "llm_failed"}
        if cached.status in cached_summary_statuses and cached.canonical_summary:
            item["summary"] = cached.canonical_summary
        return record

    source_text = native_text
    origin = native_origin
    http_status = None
    fetched_length = 0
    fetch_error = ""

    if browser_fetch_allowed and strategy == "browser_fetch":
        browser_text, browser_status, browser_http_status, browser_length, browser_error = (
            _fetch_browser_source_text(url, feed_conf, enrich_cfg, limiter)
        )
        if browser_status == "ok":
            source_text = browser_text
            origin = "browser_markdown"
            http_status = browser_http_status
            fetched_length = browser_length
        elif not native_text:
            cache.put(
                url,
                browser_status,
                browser_http_status,
                "",
                browser_length,
                "browser_markdown",
                source,
                browser_error,
            )
            return _record(
                item,
                browser_status,
                browser_error,
                source_text_origin="browser_markdown",
                native_length=native_length,
                fetched_length=browser_length,
                http_status=browser_http_status,
            )
        else:
            fetch_error = f"browser {browser_status}: {browser_error}".strip()

    if http_fetch_allowed and origin != "browser_markdown":
        fetched_text, fetch_status, http_status, fetched_length, error = _fetch_source_text(
            url, feed_conf, enrich_cfg, limiter
        )
        if fetch_status == "ok":
            source_text = fetched_text
            origin = "fetched_html"
        elif browser_fetch_allowed:
            browser_text, browser_status, browser_http_status, browser_length, browser_error = (
                _fetch_browser_source_text(url, feed_conf, enrich_cfg, limiter)
            )
            if browser_status == "ok":
                source_text = browser_text
                origin = "browser_markdown"
                http_status = browser_http_status
                fetched_length = browser_length
                fetch_error = f"fetch {fetch_status}: {error}".strip()
            elif native_text and native_origin in {"rss_body", "content", "content_encoded"}:
                fetch_error = "; ".join(
                    part
                    for part in [
                        f"fetch {fetch_status}: {error}".strip(),
                        f"browser {browser_status}: {browser_error}".strip(),
                    ]
                    if part
                )
            else:
                cache.put(
                    url,
                    browser_status,
                    browser_http_status,
                    "",
                    browser_length,
                    "browser_markdown",
                    source,
                    browser_error,
                )
                return _record(
                    item,
                    browser_status,
                    browser_error,
                    source_text_origin="browser_markdown",
                    native_length=native_length,
                    fetched_length=browser_length,
                    http_status=browser_http_status,
                )
        elif native_text and native_origin in {"rss_body", "content", "content_encoded"}:
            fetch_error = f"fetch {fetch_status}: {error}".strip()
        else:
            cache.put(url, fetch_status, http_status, "", fetched_length, "fetched_html", source, error)
            return _record(
                item,
                fetch_status,
                error,
                source_text_origin="fetched_html",
                native_length=native_length,
                fetched_length=fetched_length,
                http_status=http_status,
            )

    if not source_text:
        return _record(
            item,
            "no_source_text",
            "",
            source_text_origin=origin,
            native_length=native_length,
            http_status=http_status,
        )

    canonical = _canonical_summary(
        source_text,
        enrich_cfg,
        system_prompt,
        model_config,
    )
    if fetch_error:
        canonical.error = "; ".join(part for part in [fetch_error, canonical.error] if part)
    if not canonical.summary:
        item["summary"] = original_summary
        return _record(
            item,
            canonical.status,
            canonical.error,
            source_text_origin=origin,
            native_length=native_length,
            fetched_length=fetched_length,
            http_status=http_status,
            fallback_reason=canonical.fallback_reason,
            rejected_summary_preview=canonical.rejected_summary_preview,
        )

    item["summary"] = canonical.summary
    raw_length = len(source_text)
    cache.put(
        url,
        canonical.status,
        http_status,
        canonical.summary,
        raw_length,
        origin,
        source,
        canonical.error,
        fallback_reason=canonical.fallback_reason,
        rejected_summary_preview=canonical.rejected_summary_preview,
    )
    return _record(
        item,
        canonical.status,
        canonical.error,
        source_text_origin=origin,
        native_length=native_length,
        fetched_length=fetched_length,
        summary_length=len(canonical.summary),
        http_status=http_status,
        fallback_reason=canonical.fallback_reason,
        rejected_summary_preview=canonical.rejected_summary_preview,
    )


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


def _canonical_summary(
    source_text: str,
    enrich_cfg: dict,
    system_prompt: str,
    model_config: dict | None,
) -> _CanonicalResult:
    max_chars = int(enrich_cfg.get("canonical_summary_max_chars", 700))
    summarize_above = int(enrich_cfg.get("summarize_above_chars", 800))

    if not needs_distillation(source_text, summarize_above):
        return _CanonicalResult(
            sanitize_source_content(source_text, max_chars=max_chars),
            "ok",
        )

    if not model_config:
        return _fallback_canonical_result(
            source_text,
            max_chars,
            "no_model_config",
        )

    user_content = (
        "Normalize the following source text to a 500-700 character digest summary.\n\n"
        f"{source_text}"
    )
    try:
        summary = call_llm(
            system_prompt,
            user_content,
            model_config,
            max_retries=2,
            json_mode=False,
            stream=False,
        )
    except Exception as exc:
        return _fallback_canonical_result(
            source_text,
            max_chars,
            "llm_error",
            error=str(exc),
        )

    summary = sanitize_source_content((summary or "").strip(), max_chars=max_chars)
    if not summary:
        return _fallback_canonical_result(
            source_text,
            max_chars,
            "empty_response",
        )
    rejection_reason = _llm_summary_rejection_reason(summary, source_text)
    if rejection_reason:
        return _fallback_canonical_result(
            source_text,
            max_chars,
            rejection_reason,
            rejected_summary=summary,
        )
    return _CanonicalResult(summary, "ok")


def _fallback_canonical_result(
    source_text: str,
    max_chars: int,
    fallback_reason: str,
    *,
    error: str = "",
    rejected_summary: str = "",
) -> _CanonicalResult:
    """Return a usable source-derived summary when normalizer output is unusable."""
    summary = sanitize_source_content(source_text, max_chars=max_chars)
    rejected_preview = sanitize_source_content(rejected_summary, max_chars=300)
    if summary:
        return _CanonicalResult(
            summary,
            "normalizer_fallback",
            error or f"normalizer fallback: {fallback_reason}",
            fallback_reason=fallback_reason,
            rejected_summary_preview=rejected_preview,
        )
    return _CanonicalResult(
        "",
        "llm_failed",
        error or f"normalizer failed: {fallback_reason}",
        fallback_reason=fallback_reason,
        rejected_summary_preview=rejected_preview,
    )


def _looks_like_bad_llm_summary(summary: str, source_text: str) -> bool:
    """Reject meta-reasoning or unusably short summaries from normalizer models."""
    return bool(_llm_summary_rejection_reason(summary, source_text))


def _llm_summary_rejection_reason(summary: str, source_text: str) -> str:
    """Return a stable reason when normalizer output is not safe to use."""
    lowered = summary[:300].lower()
    meta_markers = (
        "the user wants",
        "the source text is",
        "let me analyze",
        "let me identify",
        "i need to",
        "i'll create",
        "key points from the article",
        "core substance",
        "not article content",
    )
    for marker in meta_markers:
        if marker in lowered:
            return f"meta_response:{marker}"
    if len(source_text) >= 800 and len(summary) < 80:
        return "too_short"
    return ""


def _record(
    item: dict,
    status: str,
    error: str,
    *,
    source_text_origin: str = "",
    native_length: int = 0,
    fetched_length: int = 0,
    summary_length: int = 0,
    http_status: int | None = None,
    fallback_reason: str = "",
    rejected_summary_preview: str = "",
) -> dict:
    record = {
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "status": status,
        "source_text_origin": source_text_origin,
        "native_length": native_length,
        "fetched_length": fetched_length,
        "summary_length": summary_length,
        "http_status": http_status,
        "error": error,
    }
    if fallback_reason:
        record["fallback_reason"] = fallback_reason
    if rejected_summary_preview:
        record["rejected_summary_preview"] = rejected_summary_preview
    return record
