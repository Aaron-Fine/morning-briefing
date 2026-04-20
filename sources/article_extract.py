"""Article body extraction and paywall classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import trafilatura

_PAYWALL_HINTS = ("subscribe", "sign in", "paywall", "log in to continue")


@dataclass
class ExtractResult:
    status: str
    text: str
    raw_length: int


def _looks_like_paywall(text: str) -> bool:
    head = (text or "")[:500].lower()
    return any(hint in head for hint in _PAYWALL_HINTS)


def extract_article(html: Optional[str], min_body_chars: int = 300) -> ExtractResult:
    """Extract article body text from HTML."""
    if not html:
        return ExtractResult("extraction_failed", "", 0)

    try:
        text = trafilatura.extract(html) or ""
    except Exception:
        text = ""

    text = text.strip()
    raw_length = len(text)
    if raw_length >= min_body_chars:
        return ExtractResult("ok", text, raw_length)
    if text and _looks_like_paywall(text):
        return ExtractResult("paywall", text, raw_length)
    return ExtractResult("extraction_failed", text, raw_length)
