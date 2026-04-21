"""Disk-backed article enrichment cache."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_CACHE_VERSION = 2


@dataclass
class CacheEntry:
    url: str
    fetched_at: datetime
    status: str
    http_status: Optional[int]
    raw_length: int
    summary_length: int
    canonical_summary: str
    source_text_origin: str
    source_name: str
    error: str


class ArticleCache:
    def __init__(
        self,
        cache_dir: Path,
        ttl_days: int = 30,
        failure_backoff_hours: int = 24,
    ) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = timedelta(days=ttl_days)
        self._backoff = timedelta(hours=failure_backoff_hours)

    def _path_for(self, url: str) -> Path:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self._dir / f"{key}.json"

    def get(self, url: str) -> Optional[CacheEntry]:
        path = self._path_for(url)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(data["fetched_at"])
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            return None
        if data.get("cache_version") != _CACHE_VERSION:
            return None

        age = datetime.now(timezone.utc) - fetched_at
        status = data.get("status", "")
        if status == "ok" and age <= self._ttl:
            return _entry_from_dict(data, fetched_at)
        if status != "ok" and age <= self._backoff:
            return _entry_from_dict(data, fetched_at)
        return None

    def put(
        self,
        url: str,
        status: str,
        http_status: Optional[int],
        canonical_summary: str,
        raw_length: int,
        source_text_origin: str,
        source_name: str,
        error: str,
    ) -> None:
        data = {
            "cache_version": _CACHE_VERSION,
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "http_status": http_status,
            "raw_length": raw_length,
            "summary_length": len(canonical_summary or ""),
            "canonical_summary": canonical_summary,
            "source_text_origin": source_text_origin,
            "source_name": source_name,
            "error": error,
        }
        try:
            self._path_for(url).write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            log.warning(f"Failed to write cache entry for {url}: {exc}")

    def prune(self) -> int:
        """Remove entries older than ttl_days."""
        removed = 0
        cutoff = datetime.now(timezone.utc) - self._ttl
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                fetched_at = datetime.fromisoformat(data["fetched_at"])
            except (json.JSONDecodeError, KeyError, ValueError, OSError):
                continue
            if fetched_at < cutoff:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


def _entry_from_dict(data: dict, fetched_at: datetime) -> CacheEntry:
    summary = data.get("canonical_summary", "")
    return CacheEntry(
        url=data["url"],
        fetched_at=fetched_at,
        status=data["status"],
        http_status=data.get("http_status"),
        raw_length=data.get("raw_length", 0),
        summary_length=data.get("summary_length", len(summary)),
        canonical_summary=summary,
        source_text_origin=data.get("source_text_origin", ""),
        source_name=data.get("source_name", ""),
        error=data.get("error", ""),
    )
