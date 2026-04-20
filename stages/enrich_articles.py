"""Stage: enrich_articles — normalize RSS items to canonical summaries."""

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


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Normalize RSS item summaries from best available source text."""
    raw_sources = deepcopy(context.get("raw_sources", {}))
    items = raw_sources.get("rss", []) or []
    enrich_cfg = config.get("enrich_articles", {}) or {}

    if not enrich_cfg.get("enabled", True) or not items:
        return {"raw_sources": raw_sources, "enrich_articles": {"records": []}}

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
    fetch_budget_used = 0
    jobs = []
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
        if fetch_needed:
            if fetch_budget_used >= max_fetches:
                skipped_records.append(_record(item, "skipped_fetch_cap", "fetch cap hit"))
                continue
            fetch_budget_used += 1
        jobs.append((item, feed_conf, fetch_needed))

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
                item,
                feed_conf,
                fetch_needed,
                enrich_cfg,
                cache,
                limiter,
                system_prompt,
                model_config,
            ): item
            for item, feed_conf, fetch_needed in jobs
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

    raw_sources["rss"] = items
    return {"raw_sources": raw_sources, "enrich_articles": {"records": status_records}}


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


def _normalize_one(
    item: dict,
    feed_conf: dict,
    fetch_needed: bool,
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
            fetched_length=cached.raw_length if cached.source_text_origin == "fetched_html" else 0,
            summary_length=cached.summary_length,
            http_status=cached.http_status,
        )
        if cached.status in {"ok", "llm_failed"} and cached.canonical_summary:
            item["summary"] = cached.canonical_summary
        return record

    source_text = native_text
    origin = native_origin
    http_status = None
    fetched_length = 0
    fetch_error = ""

    if fetch_needed:
        fetched_text, fetch_status, http_status, fetched_length, error = _fetch_source_text(
            url, feed_conf, enrich_cfg, limiter
        )
        if fetch_status == "ok":
            source_text = fetched_text
            origin = "fetched_html"
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

    summary, status, error = _canonical_summary(
        source_text,
        enrich_cfg,
        system_prompt,
        model_config,
    )
    if fetch_error:
        error = "; ".join(part for part in [fetch_error, error] if part)
    if not summary:
        item["summary"] = original_summary
        return _record(
            item,
            status,
            error,
            source_text_origin=origin,
            native_length=native_length,
            fetched_length=fetched_length,
            http_status=http_status,
        )

    item["summary"] = summary
    raw_length = len(source_text)
    cache.put(url, status, http_status, summary, raw_length, origin, source, error)
    return _record(
        item,
        status,
        error,
        source_text_origin=origin,
        native_length=native_length,
        fetched_length=fetched_length,
        summary_length=len(summary),
        http_status=http_status,
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


def _canonical_summary(
    source_text: str,
    enrich_cfg: dict,
    system_prompt: str,
    model_config: dict | None,
) -> tuple[str, str, str]:
    max_chars = int(enrich_cfg.get("canonical_summary_max_chars", 700))
    summarize_above = int(enrich_cfg.get("summarize_above_chars", 800))

    if not needs_distillation(source_text, summarize_above):
        return sanitize_source_content(source_text, max_chars=max_chars), "ok", ""

    if not model_config:
        return (
            sanitize_source_content(source_text, max_chars=max_chars),
            "llm_failed",
            "no model_config",
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
        return (
            sanitize_source_content(source_text, max_chars=max_chars),
            "llm_failed",
            str(exc),
        )

    summary = sanitize_source_content((summary or "").strip(), max_chars=max_chars)
    if not summary:
        return (
            sanitize_source_content(source_text, max_chars=max_chars),
            "llm_failed",
            "empty LLM response",
        )
    return summary, "ok", ""


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
) -> dict:
    return {
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
