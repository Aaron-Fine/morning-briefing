"""Candidate classification and fetch-budget allocation for enrichment."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse


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


def _health_tier(feed_conf: dict) -> str:
    return (feed_conf or {}).get("health", "active")


def _allocate_budget(
    candidates: list[_Candidate],
    *,
    attr_needed: str,
    attr_allowed: str,
    cap: int,
    skipped_status: str,
    skipped_records: list[dict],
    make_record,
) -> None:
    budget = max(0, int(cap or 0))
    needed = [candidate for candidate in candidates if getattr(candidate, attr_needed)]
    needed.sort(key=lambda candidate: candidate.priority)
    for idx, candidate in enumerate(needed):
        if idx < budget:
            setattr(candidate, attr_allowed, True)
            continue
        skipped_records.append(
            make_record(
                candidate.item,
                skipped_status,
                f"{skipped_status.replace('_', ' ')} hit; "
                f"rank_reason={candidate.priority_reason}; candidates={len(needed)}",
                source_text_origin="",
                native_length=len(candidate.native_text or ""),
            )
        )


def _allocate_tiered_budget(
    candidates: list[_Candidate],
    *,
    attr_needed: str,
    attr_allowed: str,
    tier_caps: dict[str, int],
    skipped_status: str,
    skipped_records: list[dict],
    make_record,
) -> dict[str, dict]:
    """Allocate budget per health tier, returning per-tier usage stats."""
    # Group candidates by tier that need this fetch type
    by_tier: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        if not getattr(candidate, attr_needed):
            continue
        tier = _health_tier(candidate.feed_conf)
        by_tier.setdefault(tier, []).append(candidate)

    # Sort within each tier by priority
    for tier in by_tier:
        by_tier[tier].sort(key=lambda c: c.priority)

    stats: dict[str, dict] = {}
    for tier, tier_candidates in by_tier.items():
        cap = tier_caps.get(tier, 0)
        budget = max(0, int(cap or 0))
        allowed = 0
        skipped = 0
        for idx, candidate in enumerate(tier_candidates):
            if idx < budget:
                setattr(candidate, attr_allowed, True)
                allowed += 1
            else:
                skipped += 1
                skipped_records.append(
                    make_record(
                        candidate.item,
                        skipped_status,
                        f"{skipped_status.replace('_', ' ')} hit; "
                        f"tier={tier}; rank_reason={candidate.priority_reason}; "
                        f"candidates={len(tier_candidates)}; cap={budget}",
                        source_text_origin="",
                        native_length=len(candidate.native_text or ""),
                    )
                )
        stats[tier] = {
            "needed": len(tier_candidates),
            "allowed": allowed,
            "skipped_by_cap": skipped,
            "cap": budget,
        }
    return stats
