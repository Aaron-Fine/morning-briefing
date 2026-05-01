"""Stage: enrich_articles — orchestration and per-item normalization."""

from __future__ import annotations

import importlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path

from sources.article_cache import ArticleCache
from sources.article_content import (
    best_native_text,
    needs_fetch,
    resolve_strategy,
)
from utils.prompts import load_prompt

from .canonical import _canonical_summary
from .fetch import resolve_source_text
from .scheduling import (
    _allocate_budget,
    _browser_fetch_candidate,
    _candidate_priority,
    _Candidate,
    _dedup_by_url,
    _HostLimiter,
)

log = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "article_bodies"
_DEFAULT_MAX_PARALLEL = 4


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

    feeds = config.get("rss", {}).get("feeds", []) or []
    _require_browser_runtime(enrich_cfg, feeds)

    cache = ArticleCache(
        Path(config.get("_test_cache_dir") or _DEFAULT_CACHE_DIR),
        ttl_days=enrich_cfg.get("cache_ttl_days", 30),
        failure_backoff_hours=enrich_cfg.get("cache_failure_backoff_hours", 24),
    )
    pruned = cache.prune()
    if pruned:
        log.info(f"enrich_articles: pruned {pruned} expired cache entries")

    feeds_by_name = {f.get("name"): f for f in feeds}
    canonical_by_url, order = _dedup_by_url(items)

    max_fetches = int(enrich_cfg.get("max_fetches_per_run", 40))
    max_browser_fetches = int(enrich_cfg.get("max_browser_fetches_per_run", 0))
    browser_enabled = bool(enrich_cfg.get("browser_fetch_enabled", False))
    candidates: list[_Candidate] = []
    skipped_records: list[dict] = []
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
        make_record=_record,
    )
    _allocate_budget(
        candidates,
        attr_needed="browser_fetch_candidate",
        attr_allowed="browser_fetch_allowed",
        cap=max_browser_fetches,
        skipped_status="skipped_browser_fetch_cap",
        skipped_records=skipped_records,
        make_record=_record,
    )
    jobs = sorted(candidates, key=lambda candidate: candidate.priority)

    limiter = _HostLimiter(
        enrich_cfg.get("per_host_concurrency", 2),
        enrich_cfg.get("per_host_min_interval_ms", 500),
    )
    system_prompt = load_prompt("enrich_article_system.md")
    status_records = list(skipped_records)
    max_parallel = int(
        config.get("pipeline", {})
        .get("concurrency", {})
        .get("enrich_articles", _DEFAULT_MAX_PARALLEL)
    )

    with ThreadPoolExecutor(max_workers=min(max_parallel, len(jobs) or 1)) as pool:
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


def _require_browser_runtime(enrich_cfg: dict, feeds: list[dict]) -> None:
    """Fail fast if browser fetching is configured but Crawl4AI isn't installed.

    Silently degrading ~15 feeds at once (browser_fetch_enabled controls the
    whole fleet) was the old behavior and tended to hide install issues in prod.
    """
    browser_enabled = bool(enrich_cfg.get("browser_fetch_enabled", False))
    has_browser_feed = any(
        ((feed or {}).get("enrich", {}) or {}).get("strategy") == "browser_fetch"
        for feed in feeds or []
    )
    if not (browser_enabled and has_browser_feed):
        return
    try:
        importlib.import_module("crawl4ai")
    except Exception as exc:
        raise RuntimeError(
            "enrich_articles: browser_fetch_enabled is true and at least one "
            "feed has strategy: browser_fetch, but Crawl4AI is not importable "
            f"({exc}). Install crawl4ai or disable browser_fetch_enabled."
        ) from exc


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
        if _ignore_cached_native_entry(cached, native_text, enrich_cfg):
            cached = None
        else:
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

    attempt = resolve_source_text(
        url=url,
        feed_conf=feed_conf,
        strategy=strategy,
        native_text=native_text,
        native_origin=native_origin,
        http_fetch_allowed=http_fetch_allowed,
        browser_fetch_allowed=browser_fetch_allowed,
        enrich_cfg=enrich_cfg,
        limiter=limiter,
    )

    if attempt.terminal:
        cache.put(
            url,
            attempt.status,
            attempt.http_status,
            "",
            attempt.fetched_length,
            attempt.origin,
            source,
            attempt.error,
        )
        return _record(
            item,
            attempt.status,
            attempt.error,
            source_text_origin=attempt.origin,
            native_length=native_length,
            fetched_length=attempt.fetched_length,
            http_status=attempt.http_status,
        )

    source_text = attempt.text
    origin = attempt.origin
    fetch_error = attempt.error
    http_status = attempt.http_status
    fetched_length = attempt.fetched_length

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
        _canonical_cfg_for_origin(enrich_cfg, origin),
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


def _canonical_cfg_for_origin(enrich_cfg: dict, origin: str) -> dict:
    """Let native RSS text pass through more often than fetched article bodies."""
    native_threshold = enrich_cfg.get("summarize_native_above_chars")
    if not native_threshold or origin not in {
        "rss_body",
        "content",
        "content_encoded",
        "summary",
        "description",
    }:
        return enrich_cfg
    cfg = dict(enrich_cfg)
    cfg["summarize_above_chars"] = int(native_threshold)
    return cfg


def _ignore_cached_native_entry(cached, native_text: str, enrich_cfg: dict) -> bool:
    """Ignore old native normalizations when the native threshold now passes through."""
    native_threshold = enrich_cfg.get("summarize_native_above_chars")
    if not native_threshold or cached.source_text_origin not in {
        "rss_body",
        "content",
        "content_encoded",
        "summary",
        "description",
    }:
        return False
    return len(native_text or "") < int(native_threshold)


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
