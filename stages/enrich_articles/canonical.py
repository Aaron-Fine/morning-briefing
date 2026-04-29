"""LLM normalization of source text into a canonical digest summary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from morning_digest.llm import call_llm
from morning_digest.sanitize import sanitize_source_content
from sources.article_content import needs_distillation

DEFAULT_META_MARKERS: tuple[str, ...] = (
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


@dataclass
class _CanonicalResult:
    summary: str
    status: str
    error: str = ""
    fallback_reason: str = ""
    rejected_summary_preview: str = ""


def _meta_markers(enrich_cfg: dict | None) -> tuple[str, ...]:
    guard = ((enrich_cfg or {}).get("guard") or {})
    configured = guard.get("meta_markers")
    if not configured:
        return DEFAULT_META_MARKERS
    return tuple(
        str(marker).strip().lower()
        for marker in configured
        if str(marker).strip()
    )


def _llm_summary_rejection_reason(
    summary: str,
    source_text: str,
    meta_markers: Sequence[str] | None = None,
) -> str:
    """Return a stable reason when normalizer output is not safe to use."""
    markers = tuple(meta_markers) if meta_markers is not None else DEFAULT_META_MARKERS
    lowered = summary[:300].lower()
    for marker in markers:
        if marker in lowered:
            return f"meta_response:{marker}"
    if len(source_text) >= 800 and len(summary) < 80:
        return "too_short"
    return ""


def _looks_like_bad_llm_summary(summary: str, source_text: str) -> bool:
    """Reject meta-reasoning or unusably short summaries from normalizer models."""
    return bool(_llm_summary_rejection_reason(summary, source_text))


def _canonical_summary(
    source_text: str,
    enrich_cfg: dict,
    system_prompt: str,
    model_config: dict | None,
) -> _CanonicalResult:
    max_chars = int(enrich_cfg.get("canonical_summary_max_chars", 700))
    summarize_above = int(enrich_cfg.get("summarize_above_chars", 800))
    markers = _meta_markers(enrich_cfg)

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
    rejection_reason = _llm_summary_rejection_reason(summary, source_text, markers)
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
