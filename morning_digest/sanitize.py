"""Security Layer 1 — Input Sanitization.

Sanitizes untrusted source content (RSS summaries, transcript text) before it
enters any LLM prompt. Goals:
  - Strip obvious injection preamble patterns.
  - Escape JSON-structural sequences that could corrupt LLM JSON output.
  - Truncate to prevent context flooding.
  - Preserve legitimate content — false positives are worse than missed injections
    for a news analysis pipeline.

All operations are non-blocking: this module never raises or drops a source
entirely. Stripped lines are logged at DEBUG level for review.
"""

import logging
from html.parser import HTMLParser

log = logging.getLogger(__name__)

# Lines starting with these patterns (case-insensitive) are stripped.
_INJECTION_PREFIXES = (
    "system:",
    "assistant:",
    "ignore ",
    "important instruction",
    "new instructions",
    "override:",
    "you are now",
    "forget everything",
    "[system]",
    "[assistant]",
    "<system>",
    "<assistant>",
)

# Lines containing these substrings (case-insensitive) are stripped.
_INJECTION_SUBSTRINGS = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard the above",
    "you must now",
    "your new role is",
    "act as if you are",
    "pretend you are",
    "disregard your previous",
)

# JSON-structural sequences that could prematurely close the object the model
# is generating. We replace these with their Unicode equivalents so they are
# preserved as readable text without structural ambiguity.
_JSON_ESCAPE_MAP = {
    '"}': '"\ufffd',  # closing quote + brace → replaced with replacement char
    "}]": "\ufffd]",  # closing brace + bracket → replaced
    "}}": "\ufffd\ufffd",  # double closing brace → replaced
}

_MAX_RSS_SUMMARY_CHARS = 500
_MAX_TRANSCRIPT_CHARS = 8000  # ~1500 words; compress stage will further reduce


class _StripTags(HTMLParser):
    """Minimal HTML-tag stripper."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def result(self) -> str:
        return "".join(self._parts)


def _strip_html(text: str) -> str:
    parser = _StripTags()
    parser.feed(text)
    return parser.result()


def _strip_injection_lines(text: str) -> str:
    lines = text.splitlines()
    clean: list[str] = []
    for line in lines:
        lower = line.strip().lower()
        if any(lower.startswith(p) for p in _INJECTION_PREFIXES):
            log.debug(f"sanitize: stripped injection-prefix line: {line[:80]!r}")
            continue
        if any(s in lower for s in _INJECTION_SUBSTRINGS):
            log.debug(f"sanitize: stripped injection-substring line: {line[:80]!r}")
            continue
        clean.append(line)
    return "\n".join(clean)


def _escape_json_structure(text: str) -> str:
    """Replace sequences that could corrupt LLM JSON output."""
    for pattern, replacement in _JSON_ESCAPE_MAP.items():
        text = text.replace(pattern, replacement)
    return text


def sanitize_source_content(text: str, max_chars: int | None = None) -> str:
    """Sanitize a single piece of untrusted source content.

    Args:
        text:      Raw text from an RSS summary or transcript chunk.
        max_chars: Character cap. If None, uses _MAX_RSS_SUMMARY_CHARS.

    Returns:
        Sanitized text, truncated to max_chars.
    """
    if not text:
        return text

    cap = max_chars if max_chars is not None else _MAX_RSS_SUMMARY_CHARS

    # 1. Strip HTML tags
    text = _strip_html(text)

    # 2. Strip injection-patterned lines
    text = _strip_injection_lines(text)

    # 3. Escape JSON-structural sequences
    text = _escape_json_structure(text)

    # 4. Truncate
    if len(text) > cap:
        if cap <= 0:
            text = ""
        elif cap == 1:
            text = "…"
        else:
            text = text[: cap - 1].rstrip() + "…"

    return text.strip()


def sanitize_rss_item(item: dict) -> dict:
    """Sanitize the summary field of a single RSS item dict (in place copy)."""
    result = dict(item)
    if "summary" in result:
        result["summary"] = sanitize_source_content(
            result["summary"], _MAX_RSS_SUMMARY_CHARS
        )
    if "title" in result:
        # Titles are short — strip injection patterns but don't truncate aggressively
        result["title"] = _strip_injection_lines(_strip_html(result["title"]))[:200]
    return result


def sanitize_transcript(text: str) -> str:
    """Sanitize a raw transcript before compression."""
    return sanitize_source_content(text, _MAX_TRANSCRIPT_CHARS)


def sanitize_all_sources(source_data: dict) -> dict:
    """Run sanitization over all source collections in raw_sources.

    Returns a new dict with sanitized content. Does not mutate input.
    """
    result = dict(source_data)

    if "rss" in result:
        result["rss"] = [sanitize_rss_item(item) for item in result["rss"]]

    if "local_news" in result:
        result["local_news"] = [
            sanitize_rss_item(item) for item in result["local_news"]
        ]

    if "analysis_transcripts" in result:
        sanitized_transcripts = []
        for t in result["analysis_transcripts"]:
            t_copy = dict(t)
            if "transcript" in t_copy:
                t_copy["transcript"] = sanitize_transcript(t_copy["transcript"])
            sanitized_transcripts.append(t_copy)
        result["analysis_transcripts"] = sanitized_transcripts

    return result
