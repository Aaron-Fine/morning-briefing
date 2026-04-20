"""Source-text selection and strategy helpers for article enrichment."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

VALID_STRATEGIES = {"auto", "rss_only", "fetch", "fetch_with_cookies", "skip"}


class _StripTags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.extend(data.splitlines())

    def text(self) -> str:
        lines = (" ".join(part.split()) for part in self._parts)
        return "\n".join(line for line in lines if line)


def _clean_text(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    parser = _StripTags()
    try:
        parser.feed(text)
        text = parser.text()
    except Exception:
        text = "\n".join(
            " ".join(line.split()) for line in text.splitlines() if line.strip()
        )
    return "\n".join(
        " ".join(line.split()) for line in text.splitlines() if line.strip()
    ).strip()


def _content_values(item: dict) -> list[str]:
    values: list[str] = []
    content = item.get("content") or []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                values.append(part.get("value", "") or "")
            elif part:
                values.append(str(part))
    elif isinstance(content, dict):
        values.append(content.get("value", "") or "")
    return values


def best_native_text(item: dict) -> tuple[str, str]:
    """Return (text, origin), preferring full body-like RSS fields."""
    candidates = [
        ("rss_body", item.get("_rss_body", "")),
        ("content", _content_values(item)),
        ("content_encoded", item.get("content_encoded", "")),
        ("summary", item.get("summary", "")),
        ("description", item.get("description", "")),
    ]

    for origin, value in candidates:
        values = value if isinstance(value, list) else [value]
        for candidate in values:
            text = _clean_text(candidate)
            if text:
                return text, origin
    return "", "none"


def resolve_strategy(feed_conf: dict) -> str:
    """Resolve explicit strategy plus legacy skip/fetch flags."""
    enrich = (feed_conf or {}).get("enrich", {}) or {}
    if enrich.get("skip", False):
        return "skip"

    strategy = enrich.get("strategy")
    if strategy in VALID_STRATEGIES:
        return strategy

    if enrich.get("fetch_article", False):
        return "fetch_with_cookies" if enrich.get("cookies_file") else "fetch"

    return "auto"


def needs_fetch(source_text: str, strategy: str, min_usable_chars: int) -> bool:
    """Return whether article HTML should be fetched."""
    if strategy in {"skip", "rss_only"}:
        return False
    if strategy in {"fetch", "fetch_with_cookies"}:
        return True
    return len(source_text or "") < min_usable_chars


def needs_distillation(source_text: str, summarize_above_chars: int) -> bool:
    """Return whether source text should go through the LLM normalizer."""
    return len(source_text or "") >= summarize_above_chars
