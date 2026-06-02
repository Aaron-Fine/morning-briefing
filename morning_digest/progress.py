"""Runtime observability: live progress logging + heartbeat.

Thread-safe because analyze_domain runs desks across a ThreadPoolExecutor.
No metrics live here — this is liveness only (see morning_digest/metrics.py).
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

log = logging.getLogger("morning_digest.progress")

_lock = threading.Lock()
_in_flight: dict[str, float] = {}


def reset() -> None:
    with _lock:
        _in_flight.clear()


def in_flight_labels() -> list[str]:
    with _lock:
        return list(_in_flight)


@contextmanager
def track(label: str) -> Iterator[None]:
    start = time.monotonic()
    with _lock:
        _in_flight[label] = start
    log.info("  %s: start", label)
    try:
        yield
    finally:
        with _lock:
            _in_flight.pop(label, None)
        log.info("  %s: done %.1fs", label, time.monotonic() - start)


def heartbeat_line() -> str | None:
    now = time.monotonic()
    with _lock:
        if not _in_flight:
            return None
        labels = list(_in_flight)
        longest = max(now - t for t in _in_flight.values())
    shown = ", ".join(labels[:5]) + ("…" if len(labels) > 5 else "")
    return f"[hb] waiting on {len(labels)} op(s): {shown} ({longest:.0f}s)"


class Heartbeat:
    """Daemon that logs the in-flight set every interval_s seconds."""

    def __init__(self, interval_s: float = 15.0):
        self.interval_s = interval_s
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self.interval_s <= 0:
            return
        if self._thread is not None and self._thread.is_alive():
            return  # already running; don't orphan the live thread
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            line = heartbeat_line()
            if line:
                log.info(line)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
