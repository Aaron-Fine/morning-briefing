# RSS Article Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade thin/empty RSS summaries by fetching article bodies, extracting with trafilatura, and distilling via a cheap LLM pass — all transparent to downstream stages, so they see a single unified `summary` field regardless of whether content came from the RSS feed or a fetched article.

**Architecture:** Three pieces land in sequence: (1) a body-field fallback in `sources/rss_feeds.py` that recovers `content:encoded` bodies the current parser drops; (2) a new `enrich_articles` pipeline stage between `collect` and `compress` that fetches qualifying items via `curl-cffi` (Chrome TLS fingerprint), extracts with `trafilatura`, distills via Fireworks, and caches to disk with a 30-day TTL; (3) a standalone audit tool at `scripts/audit_rss_quality.py` that reads existing artifacts and ranks feeds by quality. Downstream stages remain unaware — same schema, same code path, enriched items and native-RSS items both arrive as `item["summary"]`.

**Tech Stack:** Python 3.12, `feedparser`, `curl-cffi` (new), `trafilatura` (new), `pytest`, Fireworks LLM via existing `morning_digest.llm.call_llm`, Docker (`python:3.12-slim` base).

**Spec:** `docs/superpowers/specs/2026-04-19-rss-article-enrichment-design.md`

**Commit/push discipline:** One feature per commit; stage files explicitly (`git add <file>`); commit at end of every task; push at each of the three natural batches (Task 2 end, Task 9 end, Task 13 end). Never `git add -A` / `git add .`.

---

## File Structure

**New files:**
- `sources/article_fetch.py` — curl-cffi HTTP client + Netscape cookies.txt loader. Isolated so tests can mock the HTTP boundary cleanly.
- `sources/article_extract.py` — trafilatura wrapper + paywall heuristic classifier. Pure functions over HTML bytes.
- `sources/article_cache.py` — disk cache CRUD (`get`, `put`, `prune`). Read/write JSON files keyed by `sha1(url)`.
- `stages/enrich_articles.py` — pipeline stage orchestration: dedup, decision, concurrency, LLM distillation, artifact emission.
- `prompts/enrich_article_system.md` — system prompt for article distillation (300-500 word output).
- `scripts/audit_rss_quality.py` — standalone audit tool.
- `tests/test_rss_feeds_body_fallback.py` — pre-work fix coverage.
- `tests/test_article_fetch.py` — cookies loader + client wiring.
- `tests/test_article_extract.py` — extraction + paywall heuristic.
- `tests/test_article_cache.py` — cache hit/miss/expiry/corrupt.
- `tests/test_enrich_articles.py` — decision logic, dedup, failure modes.
- `tests/test_audit_rss_quality.py` — audit scoring and empty input.

**Modified files:**
- `sources/rss_feeds.py` — add `_entry_body()` helper; swap call site.
- `requirements.txt` — add `trafilatura>=1.8`, `curl-cffi>=0.7`.
- `config.yaml` — add `enrich_articles:` global block, register stage, add per-feed `enrich:` blocks on pre-seeded feeds.
- `docker-compose.yml` — mount `./cookies:/app/cookies:ro`.
- `.gitignore` — add `cookies/`.
- `.dockerignore` — add `cookies/` (create file if absent).
- `prompts/analyze_domain_system.md` — enrichment context note.
- `prompts/seam_candidates.md`, `prompts/seam_annotations.md` — enrichment context note.
- `prompts/cross_domain_plan.md`, `prompts/cross_domain_execute.md`, `prompts/cross_domain_system.md` — enrichment context note.
- `README.md` — stage list, mermaid, Article enrichment / Authenticated fetches / Diagnostics subsections, deps note.
- `CLAUDE.md` — pointer to `enrich_articles.json` artifact and audit tool.

---

## Task 0: Pre-flight sanity checks

**Files:** none (verification only). Capture results in a short scratch note you paste into your response to the user — not committed.

- [ ] **Step 0.1: Verify curl-cffi wheel works in the Docker image**

Run:
```bash
cd /home/aaron/Morning-Digest
docker compose run --rm --entrypoint "" morning-digest \
  pip install curl-cffi==0.7.4 trafilatura==1.12.2
docker compose run --rm --entrypoint "" morning-digest \
  python -c "from curl_cffi import requests; r = requests.get('https://example.com', impersonate='chrome'); print(r.status_code, len(r.text))"
```
Expected: `200 <some positive length>`. If install fails (wheel missing) or the Chrome impersonation errors out, stop and report — the design assumes these work on `python:3.12-slim`.

- [ ] **Step 0.2: Verify trafilatura quality on Substack DOM**

Run:
```bash
docker compose run --rm --entrypoint "" morning-digest python - <<'PY'
import trafilatura
urls = [
    "https://slowboring.com/p/one-cheer-for-the-democratic-party",
    "https://adamtooze.substack.com/p/chartbook-newsletter-101",
    "https://simonwillison.net/2024/Sep/10/",
]
for url in urls:
    html = trafilatura.fetch_url(url)
    text = trafilatura.extract(html) if html else ""
    print(f"{url}\n  extracted: {len(text) if text else 0} chars\n  first 200: {text[:200] if text else '(none)'!r}\n")
PY
```
Expected: 500+ chars of clean article prose per URL, no subscribe CTAs or navigation in the first 200 chars. If extraction is poor on Substack, note it and plan a Substack-specific fallback in Task 4.

- [ ] **Step 0.3: Verify cookies.txt round-trip**

Manual step — cannot be scripted. Ask the user to:
1. Install "Get cookies.txt LOCALLY" browser extension.
2. Log into The Atlantic.
3. Export cookies for `theatlantic.com` to `/tmp/test-atlantic.cookies.txt`.

Then run:
```bash
docker compose run --rm -v /tmp/test-atlantic.cookies.txt:/tmp/cookies.txt:ro --entrypoint "" morning-digest python - <<'PY'
from http.cookiejar import MozillaCookieJar
from curl_cffi import requests
jar = MozillaCookieJar("/tmp/cookies.txt")
jar.load(ignore_discard=True, ignore_expires=True)
print(f"jar has {len(list(jar))} cookies")
r = requests.get("https://www.theatlantic.com/", impersonate="chrome", cookies=jar)
print(f"GET homepage -> {r.status_code}, {len(r.text)} chars")
PY
```
Expected: `jar has N cookies` where N > 5; homepage fetch returns 200 and HTML containing recognizable subscriber UI strings (e.g. "My Account" or "Sign out"). If `jar.load` fails, we need an adapter — document the error and plan accordingly in Task 3.

- [ ] **Step 0.4: Confirm Fireworks quota headroom**

Ask the user to eyeball their Fireworks dashboard. The enrichment stage adds up to 40 calls/day to `minimax-m2p7` at ~500 max_tokens output. Should be <1% of any reasonable plan, but confirm.

- [ ] **Step 0.5: Summarize findings**

Write a short paragraph in your response to the user listing: (a) wheel install OK/not, (b) trafilatura Substack quality: good/mediocre/poor, (c) cookies.txt parsed OK/not, (d) quota confirmed. Any "not OK" items gate later tasks.

No commit for this task. Proceed only after user reviews the sanity-check summary.

---

## Task 1: Pre-work — body-field fallback in `rss_feeds.py`

**Files:**
- Modify: `sources/rss_feeds.py:325-373` (`_extract_feed_items` and `_items_from_parsed_feed`)
- Create: `tests/test_rss_feeds_body_fallback.py`

- [ ] **Step 1.1: Write failing tests**

Create `tests/test_rss_feeds_body_fallback.py`:
```python
"""Tests for the body-field fallback in sources.rss_feeds."""

import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.rss_feeds import _entry_body


def _entry(**fields):
    """Build a dict shaped like a feedparser entry."""
    return dict(fields)


class TestEntryBody:
    def test_returns_summary_when_present(self):
        e = _entry(summary="Short blurb", description="", content=[])
        assert _entry_body(e) == "Short blurb"

    def test_falls_back_to_description_when_summary_empty(self):
        e = _entry(summary="", description="Real description here", content=[])
        assert _entry_body(e) == "Real description here"

    def test_falls_back_to_content_encoded_when_earlier_fields_empty(self):
        e = _entry(
            summary="",
            description="",
            content=[{"value": "Full content body text"}],
        )
        assert _entry_body(e) == "Full content body text"

    def test_returns_empty_when_all_fields_missing(self):
        assert _entry_body({}) == ""

    def test_returns_empty_when_all_fields_blank(self):
        e = _entry(summary="   ", description="", content=[{"value": ""}])
        assert _entry_body(e) == ""

    def test_prefers_summary_over_description_when_both_present(self):
        e = _entry(summary="From summary", description="From description", content=[])
        assert _entry_body(e) == "From summary"

    def test_ignores_content_without_value_key(self):
        e = _entry(summary="", description="", content=[{"type": "text/html"}])
        assert _entry_body(e) == ""

    def test_handles_multiple_content_entries_uses_first(self):
        e = _entry(
            summary="",
            description="",
            content=[{"value": "First"}, {"value": "Second"}],
        )
        assert _entry_body(e) == "First"
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /home/aaron/Morning-Digest
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_rss_feeds_body_fallback.py -v
```
Expected: `ImportError: cannot import name '_entry_body'`. All tests fail with the same error.

- [ ] **Step 1.3: Add the `_entry_body` helper**

In `sources/rss_feeds.py`, add this function above `_items_from_parsed_feed` (around line 343):
```python
def _entry_body(entry) -> str:
    """Return the first non-empty body-like field from a feedparser entry.

    Some feeds (notably Nikkei Asia) ship the article text in
    <content:encoded> rather than <description>. feedparser surfaces
    those at entry.content instead of entry.summary, so we need to
    look in both places before giving up.
    """
    candidates: list[str] = [
        entry.get("summary", "") or "",
        entry.get("description", "") or "",
    ]
    content = entry.get("content") or []
    if content:
        first = content[0] if isinstance(content[0], dict) else {}
        candidates.append(first.get("value", "") or "")
    for c in candidates:
        if c and c.strip():
            return c
    return ""
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_rss_feeds_body_fallback.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 1.5: Wire `_entry_body` into the parsed-feed path**

In `sources/rss_feeds.py`, replace the `_items_from_parsed_feed` body lookup. Find:
```python
        item = {
            "source": feed_conf["name"],
            "title": entry.get("title", "").strip(),
            "url": entry.get("link", ""),
            "published": published.isoformat() if published else "",
            "summary": _clean_summary(entry.get("summary", "")),
        }
```
Replace with:
```python
        item = {
            "source": feed_conf["name"],
            "title": entry.get("title", "").strip(),
            "url": entry.get("link", ""),
            "published": published.isoformat() if published else "",
            "summary": _clean_summary(_entry_body(entry)),
        }
```

- [ ] **Step 1.6: Run the full test suite to confirm no regressions**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/ -v
```
Expected: all green. If any existing test fails because it expected the old `entry.summary`-only behavior, update the test to match the new behavior — do not revert the fix.

- [ ] **Step 1.7: Commit**

```bash
git add sources/rss_feeds.py tests/test_rss_feeds_body_fallback.py
git commit -m "$(cat <<'EOF'
Fall back to description/content:encoded when summary is empty

Feeds like Nikkei Asia publish their article text via
<content:encoded> instead of <description>; feedparser surfaces those
at entry.content, which the parsed-feed path was ignoring. Adds
_entry_body() that walks summary -> description -> content[0].value
and uses the first non-empty candidate, closing the most common
cause of 0-char summaries before the enrichment stage lands.
EOF
)"
```

---

## Task 2: Add `trafilatura` and `curl-cffi` dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 2.1: Add pinned dependencies**

Open `requirements.txt` and add two lines at the end (keeping the existing entries intact):
```
trafilatura>=1.8
curl-cffi>=0.7
```

- [ ] **Step 2.2: Rebuild the Docker image**

```bash
cd /home/aaron/Morning-Digest
docker compose build
```
Expected: successful build. If wheels for curl-cffi fail to install, stop — this was supposed to be confirmed in Task 0.

- [ ] **Step 2.3: Verify imports work in the rebuilt image**

```bash
docker compose run --rm --entrypoint "" morning-digest python -c "import curl_cffi.requests; import trafilatura; print(curl_cffi.__version__, trafilatura.__version__)"
```
Expected: prints two version strings, no errors.

- [ ] **Step 2.4: Commit**

```bash
git add requirements.txt
git commit -m "Add trafilatura and curl-cffi for article enrichment"
```

---

## Task 3: `sources/article_fetch.py` — HTTP client + cookies loader

**Files:**
- Create: `sources/article_fetch.py`
- Create: `tests/test_article_fetch.py`

- [ ] **Step 3.1: Write failing tests**

Create `tests/test_article_fetch.py`:
```python
"""Tests for sources.article_fetch: HTTP client + cookies loader."""

import sys
import os
from http.cookiejar import MozillaCookieJar
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.article_fetch import load_cookies_file, fetch_article_html, FetchResult


class TestLoadCookiesFile:
    def test_loads_valid_netscape_cookies(self, tmp_path):
        cookies_path = tmp_path / "cookies.txt"
        cookies_path.write_text(
            "# Netscape HTTP Cookie File\n"
            ".example.com\tTRUE\t/\tFALSE\t9999999999\tsession\tabc123\n"
        )
        jar = load_cookies_file(str(cookies_path))
        cookies = list(jar)
        assert len(cookies) == 1
        assert cookies[0].name == "session"
        assert cookies[0].value == "abc123"

    def test_returns_none_when_path_is_none(self):
        assert load_cookies_file(None) is None

    def test_returns_none_when_path_is_empty_string(self):
        assert load_cookies_file("") is None

    def test_returns_none_when_file_missing(self, tmp_path, caplog):
        missing = tmp_path / "does_not_exist.txt"
        result = load_cookies_file(str(missing))
        assert result is None

    def test_returns_none_on_corrupt_file(self, tmp_path):
        cookies_path = tmp_path / "bad.txt"
        cookies_path.write_text("not a cookies file at all\n")
        result = load_cookies_file(str(cookies_path))
        assert result is None


class TestFetchArticleHtml:
    def test_returns_ok_on_200(self):
        fake_response = MagicMock(status_code=200, text="<html>hi</html>")
        with patch("sources.article_fetch._session_get", return_value=fake_response):
            result = fetch_article_html("https://example.com/x", impersonate="chrome")
        assert result.status == "ok"
        assert result.http_status == 200
        assert result.html == "<html>hi</html>"
        assert result.error == ""

    def test_returns_http_error_on_non_2xx(self):
        fake_response = MagicMock(status_code=403, text="Forbidden")
        with patch("sources.article_fetch._session_get", return_value=fake_response):
            result = fetch_article_html("https://example.com/x", impersonate="chrome")
        assert result.status == "http_error"
        assert result.http_status == 403
        assert result.html == ""
        assert "403" in result.error

    def test_returns_http_error_on_exception(self):
        with patch("sources.article_fetch._session_get", side_effect=RuntimeError("boom")):
            result = fetch_article_html("https://example.com/x", impersonate="chrome")
        assert result.status == "http_error"
        assert result.http_status is None
        assert "boom" in result.error

    def test_passes_cookies_when_jar_provided(self):
        fake_response = MagicMock(status_code=200, text="ok")
        jar = MozillaCookieJar()
        with patch("sources.article_fetch._session_get", return_value=fake_response) as mock_get:
            fetch_article_html("https://example.com/x", impersonate="chrome", cookies=jar)
        _, kwargs = mock_get.call_args
        assert kwargs.get("cookies") is jar

    def test_respects_custom_user_agent(self):
        fake_response = MagicMock(status_code=200, text="ok")
        with patch("sources.article_fetch._session_get", return_value=fake_response) as mock_get:
            fetch_article_html("https://example.com/x", impersonate="chrome", user_agent="X/1.0")
        _, kwargs = mock_get.call_args
        assert kwargs.get("headers", {}).get("User-Agent") == "X/1.0"
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_article_fetch.py -v
```
Expected: `ModuleNotFoundError: sources.article_fetch`.

- [ ] **Step 3.3: Implement `sources/article_fetch.py`**

Create `sources/article_fetch.py`:
```python
"""HTTP client for article body fetches.

Thin wrapper over curl-cffi that:
  - Impersonates a real Chrome browser (TLS fingerprint, HTTP/2,
    default header set) so naive bot filters and basic Cloudflare
    challenges pass cleanly.
  - Optionally loads a Netscape cookies.txt jar for authenticated
    fetches against subscription sites (e.g. The Atlantic).
  - Never raises: returns a structured FetchResult with status code
    or error message, leaving retry/backoff decisions to the caller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from typing import Optional

from curl_cffi import requests as curl_requests

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    status: str           # "ok" | "http_error"
    http_status: Optional[int]
    html: str
    error: str


def load_cookies_file(path: Optional[str]) -> Optional[MozillaCookieJar]:
    """Load a Netscape cookies.txt file. Returns None on any failure.

    We never raise: a missing/corrupt cookies file degrades the fetch
    to an anonymous request, which is the least surprising behavior.
    Callers see the resulting paywall in the cached status if relevant.
    """
    if not path:
        return None
    try:
        jar = MozillaCookieJar(path)
        jar.load(ignore_discard=True, ignore_expires=True)
        return jar
    except FileNotFoundError:
        log.warning(f"Cookies file not found: {path}")
        return None
    except Exception as e:
        log.warning(f"Failed to load cookies file {path}: {e}")
        return None


def _session_get(url: str, **kwargs):
    """Indirection seam for tests — do not inline."""
    return curl_requests.get(url, **kwargs)


def fetch_article_html(
    url: str,
    impersonate: str = "chrome",
    timeout: int = 15,
    cookies: Optional[MozillaCookieJar] = None,
    user_agent: Optional[str] = None,
) -> FetchResult:
    """Fetch HTML from url. Never raises.

    Returns FetchResult with status="ok" on 2xx responses, "http_error"
    otherwise (network error, non-2xx, timeout, anything else).
    """
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent

    try:
        resp = _session_get(
            url,
            impersonate=impersonate,
            timeout=timeout,
            cookies=cookies,
            headers=headers or None,
            allow_redirects=True,
        )
    except Exception as e:
        return FetchResult(status="http_error", http_status=None, html="", error=str(e))

    if 200 <= resp.status_code < 300:
        return FetchResult(
            status="ok",
            http_status=resp.status_code,
            html=resp.text,
            error="",
        )
    return FetchResult(
        status="http_error",
        http_status=resp.status_code,
        html="",
        error=f"HTTP {resp.status_code}",
    )
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_article_fetch.py -v
```
Expected: all 10 tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add sources/article_fetch.py tests/test_article_fetch.py
git commit -m "Add article HTTP client with curl-cffi and cookies support

Wraps curl-cffi with Chrome impersonation for the TLS fingerprint and
a Netscape cookies.txt loader for authenticated fetches. Returns a
FetchResult rather than raising so the stage can record errors in
the disk cache and keep processing remaining items."
```

---

## Task 4: `sources/article_extract.py` — trafilatura + paywall heuristic

**Files:**
- Create: `sources/article_extract.py`
- Create: `tests/test_article_extract.py`

**Note from Task 0:** Substack-rendered HTML was NOT sanity-checked in pre-flight (the hardcoded test URLs were 404s). If integration runs show `extraction_failed` for Substack-hosted feeds (adamtooze, slowboring, etc.), first check the stored HTML for a JS-only render shell — trafilatura needs article text in the initial HTML document, not JS-injected. Mitigation if needed: add a Substack-specific fallback that pulls from the `<meta name="description">` and the first N `<p>` tags inside `<article>` before giving up.

- [ ] **Step 4.1: Write failing tests**

Create `tests/test_article_extract.py`:
```python
"""Tests for sources.article_extract."""

import sys
import os
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.article_extract import extract_article, ExtractResult


SAMPLE_ARTICLE_HTML = """
<html><body><article>
<h1>Real Article Title</h1>
<p>""" + ("This is a real paragraph of article content. " * 30) + """</p>
<p>""" + ("Another paragraph with more substance. " * 30) + """</p>
</article></body></html>
"""

SAMPLE_PAYWALL_HTML = """
<html><body><article>
<h1>Members Only</h1>
<p>Subscribe to read the full article.</p>
<p>Sign in if you're already a subscriber.</p>
</article></body></html>
"""


class TestExtractArticle:
    def test_returns_ok_with_clean_text_on_full_article(self):
        result = extract_article(SAMPLE_ARTICLE_HTML, min_body_chars=300)
        assert result.status == "ok"
        assert len(result.text) >= 300
        assert "Real Article Title" not in result.text or "paragraph" in result.text

    def test_empty_html_returns_extraction_failed(self):
        result = extract_article("", min_body_chars=300)
        assert result.status == "extraction_failed"
        assert result.text == ""

    def test_none_html_returns_extraction_failed(self):
        result = extract_article(None, min_body_chars=300)
        assert result.status == "extraction_failed"

    def test_short_body_returns_extraction_failed(self):
        short = "<html><body><p>Too short.</p></body></html>"
        result = extract_article(short, min_body_chars=300)
        assert result.status == "extraction_failed"

    def test_paywall_heuristic_matches_subscribe_in_short_body(self):
        result = extract_article(SAMPLE_PAYWALL_HTML, min_body_chars=300)
        assert result.status == "paywall"
        assert "subscrib" in result.text.lower() or result.text == ""

    def test_paywall_heuristic_catches_sign_in_wall(self):
        html = "<html><body><article><p>Please sign in to continue reading.</p></article></body></html>"
        result = extract_article(html, min_body_chars=300)
        assert result.status == "paywall"

    def test_min_body_chars_is_configurable(self):
        short = "<html><body><article><p>" + ("Short body. " * 10) + "</p></article></body></html>"
        result_strict = extract_article(short, min_body_chars=500)
        result_loose = extract_article(short, min_body_chars=50)
        assert result_strict.status == "extraction_failed"
        assert result_loose.status == "ok"

    def test_raw_length_reflects_extracted_length(self):
        result = extract_article(SAMPLE_ARTICLE_HTML, min_body_chars=300)
        assert result.raw_length == len(result.text)
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_article_extract.py -v
```
Expected: `ModuleNotFoundError: sources.article_extract`.

- [ ] **Step 4.3: Implement `sources/article_extract.py`**

Create `sources/article_extract.py`:
```python
"""Article body extraction + paywall heuristic.

Wraps trafilatura.extract() with a consistent return shape and
classifies too-short extractions as paywalls when the leading text
contains login/subscribe strings. The paywall distinction is
audit-only — behavior is identical to extraction_failed (both get
cached with the failure backoff).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import trafilatura


_PAYWALL_HINTS = ("subscribe", "sign in", "paywall", "log in to continue")


@dataclass
class ExtractResult:
    status: str          # "ok" | "extraction_failed" | "paywall"
    text: str
    raw_length: int


def _looks_like_paywall(text: str) -> bool:
    head = (text or "")[:500].lower()
    return any(hint in head for hint in _PAYWALL_HINTS)


def extract_article(html: Optional[str], min_body_chars: int = 300) -> ExtractResult:
    """Extract article body from HTML.

    Returns:
      - status="ok" with text if extraction yields >= min_body_chars of content.
      - status="paywall" if the extracted text is too short AND contains
        a login/subscribe hint — diagnostic only, behavior same as failed.
      - status="extraction_failed" for any other too-short or empty result.
    """
    if not html:
        return ExtractResult(status="extraction_failed", text="", raw_length=0)

    try:
        text = trafilatura.extract(html) or ""
    except Exception:
        text = ""

    text = text.strip()
    if len(text) >= min_body_chars:
        return ExtractResult(status="ok", text=text, raw_length=len(text))

    if text and _looks_like_paywall(text):
        return ExtractResult(status="paywall", text=text, raw_length=len(text))

    return ExtractResult(status="extraction_failed", text=text, raw_length=len(text))
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_article_extract.py -v
```
Expected: all 8 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add sources/article_extract.py tests/test_article_extract.py
git commit -m "Add trafilatura extraction with paywall heuristic

Extracts article text via trafilatura and classifies short extractions
containing login/subscribe hints as 'paywall' rather than
'extraction_failed'. The distinction is diagnostic only — both go
into the same failure-backoff path in the cache."
```

---

## Task 5: `sources/article_cache.py` — disk cache layer

**Files:**
- Create: `sources/article_cache.py`
- Create: `tests/test_article_cache.py`

- [ ] **Step 5.1: Write failing tests**

Create `tests/test_article_cache.py`:
```python
"""Tests for sources.article_cache."""

import sys
import os
import json
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.article_cache import ArticleCache, CacheEntry


@pytest.fixture
def cache_dir(tmp_path):
    d = tmp_path / "article_bodies"
    d.mkdir()
    return d


@pytest.fixture
def cache(cache_dir):
    return ArticleCache(cache_dir, ttl_days=30, failure_backoff_hours=24)


class TestArticleCache:
    def test_miss_on_missing_url(self, cache):
        assert cache.get("https://example.com/x") is None

    def test_put_then_get_returns_entry(self, cache):
        cache.put(
            url="https://example.com/x",
            status="ok",
            http_status=200,
            compressed_body="distilled body",
            raw_length=4000,
            source_name="Example",
            error="",
        )
        entry = cache.get("https://example.com/x")
        assert entry is not None
        assert entry.status == "ok"
        assert entry.compressed_body == "distilled body"
        assert entry.raw_length == 4000

    def test_ok_entry_within_ttl_is_hit(self, cache):
        cache.put("https://x/", "ok", 200, "body", 1000, "Src", "")
        assert cache.get("https://x/") is not None

    def test_ok_entry_past_ttl_is_miss(self, cache_dir):
        cache = ArticleCache(cache_dir, ttl_days=30, failure_backoff_hours=24)
        cache.put("https://x/", "ok", 200, "body", 1000, "Src", "")
        # Rewrite fetched_at to 31 days ago
        files = list(cache_dir.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        data["fetched_at"] = old
        files[0].write_text(json.dumps(data))
        assert cache.get("https://x/") is None

    def test_failure_entry_within_backoff_is_hit(self, cache):
        cache.put("https://x/", "http_error", 500, "", 0, "Src", "boom")
        assert cache.get("https://x/") is not None

    def test_failure_entry_past_backoff_is_miss(self, cache_dir):
        cache = ArticleCache(cache_dir, ttl_days=30, failure_backoff_hours=24)
        cache.put("https://x/", "http_error", 500, "", 0, "Src", "boom")
        files = list(cache_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        data["fetched_at"] = old
        files[0].write_text(json.dumps(data))
        assert cache.get("https://x/") is None

    def test_corrupt_json_is_miss(self, cache_dir, cache):
        cache.put("https://x/", "ok", 200, "body", 1000, "Src", "")
        files = list(cache_dir.glob("*.json"))
        files[0].write_text("{not valid json")
        assert cache.get("https://x/") is None

    def test_prune_removes_entries_older_than_ttl(self, cache_dir):
        cache = ArticleCache(cache_dir, ttl_days=30, failure_backoff_hours=24)
        cache.put("https://fresh/", "ok", 200, "body", 1000, "Src", "")
        cache.put("https://stale/", "ok", 200, "body", 1000, "Src", "")
        # Age the second one to 31 days
        for f in cache_dir.glob("*.json"):
            data = json.loads(f.read_text())
            if "stale" in data["url"]:
                data["fetched_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
                f.write_text(json.dumps(data))

        removed = cache.prune()
        assert removed == 1
        remaining = [json.loads(f.read_text())["url"] for f in cache_dir.glob("*.json")]
        assert remaining == ["https://fresh/"]

    def test_prune_leaves_fresh_entries_alone(self, cache):
        cache.put("https://a/", "ok", 200, "body", 1000, "Src", "")
        cache.put("https://b/", "http_error", 500, "", 0, "Src", "boom")
        assert cache.prune() == 0

    def test_sha1_keying_collision_free(self, cache):
        cache.put("https://a/x", "ok", 200, "A body", 100, "Src", "")
        cache.put("https://b/x", "ok", 200, "B body", 100, "Src", "")
        assert cache.get("https://a/x").compressed_body == "A body"
        assert cache.get("https://b/x").compressed_body == "B body"
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_article_cache.py -v
```
Expected: `ModuleNotFoundError: sources.article_cache`.

- [ ] **Step 5.3: Implement `sources/article_cache.py`**

Create `sources/article_cache.py`:
```python
"""Disk-backed article body cache.

One JSON file per URL, keyed by sha1(url). Hit policy:
  - status="ok" within ttl_days -> hit
  - non-ok within failure_backoff_hours -> hit (skip retry)
  - everything else -> miss

Corrupt files and JSON decode errors are silently treated as misses;
the stage rewrites on the next fetch attempt.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    url: str
    fetched_at: datetime
    status: str
    http_status: Optional[int]
    raw_length: int
    compressed_body: str
    source_name: str
    error: str


class ArticleCache:
    def __init__(self, cache_dir: Path, ttl_days: int = 30, failure_backoff_hours: int = 24):
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
        compressed_body: str,
        raw_length: int,
        source_name: str,
        error: str,
    ) -> None:
        data = {
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "http_status": http_status,
            "raw_length": raw_length,
            "compressed_body": compressed_body,
            "source_name": source_name,
            "error": error,
        }
        path = self._path_for(url)
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as e:
            log.warning(f"Failed to write cache entry for {url}: {e}")

    def prune(self) -> int:
        """Remove entries older than ttl_days. Returns count removed."""
        removed = 0
        cutoff = datetime.now(timezone.utc) - self._ttl
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                fetched_at = datetime.fromisoformat(data["fetched_at"])
            except (json.JSONDecodeError, KeyError, ValueError, OSError):
                # Corrupt — leave it; next get() miss will overwrite.
                continue
            if fetched_at < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


def _entry_from_dict(data: dict, fetched_at: datetime) -> CacheEntry:
    return CacheEntry(
        url=data["url"],
        fetched_at=fetched_at,
        status=data["status"],
        http_status=data.get("http_status"),
        raw_length=data.get("raw_length", 0),
        compressed_body=data.get("compressed_body", ""),
        source_name=data.get("source_name", ""),
        error=data.get("error", ""),
    )
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_article_cache.py -v
```
Expected: all 10 tests pass.

- [ ] **Step 5.5: Commit**

```bash
git add sources/article_cache.py tests/test_article_cache.py
git commit -m "Add disk-backed article body cache

JSON-per-URL keyed by sha1(url), with a 30-day TTL for successful
fetches and a 24-hour failure backoff. Corrupt files degrade to a
cache miss and get rewritten on the next fetch attempt."
```

---

## Task 6: `prompts/enrich_article_system.md`

**Files:**
- Create: `prompts/enrich_article_system.md`

- [ ] **Step 6.1: Create the prompt file**

Create `prompts/enrich_article_system.md`:
```markdown
You are an article compressor. Given the full text of a news article, produce a dense summary that preserves:
1. All concrete claims, events, and factual assertions
2. Named actors (people, organizations, countries, programs) and what each did
3. Specific numbers, dates, locations, and technical terms
4. Any clear chronology or cause-and-effect chain the article establishes
5. The article's analytical framing where it matters — what the author treats as cause vs. effect, significant vs. incidental

Strip all of the following:
- Boilerplate (site navigation, bylines, dateline formatting)
- Subscription CTAs, "read more," "related coverage," newsletter signups
- Pull quotes and pull-quote duplication of body text
- Author bios, publication metadata, ad copy
- Social-share widgets, comment counts, reaction prompts

The target length is 300–500 words. Match it closely.

Output plain text only. No JSON. No markdown headers. No preamble ("Here is a summary of...") — go directly into the content.
```

- [ ] **Step 6.2: Verify the prompt loads via `utils.prompts.load_prompt`**

```bash
docker compose run --rm --entrypoint "" morning-digest python -c "from utils.prompts import load_prompt; print(len(load_prompt('enrich_article_system.md')))"
```
Expected: prints a positive integer (the prompt file length).

- [ ] **Step 6.3: Commit**

```bash
git add prompts/enrich_article_system.md
git commit -m "Add enrich_article system prompt for article distillation"
```

---

## Task 7: `stages/enrich_articles.py` — the pipeline stage

**Files:**
- Create: `stages/enrich_articles.py`
- Create: `tests/test_enrich_articles.py`

- [ ] **Step 7.1: Write failing tests**

Create `tests/test_enrich_articles.py`:
```python
"""Tests for stages.enrich_articles."""

import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.enrich_articles import (
    run,
    _should_enrich,
    _dedup_by_url,
)


def _make_rss_items():
    return [
        {"source": "A", "title": "one", "url": "https://a/1", "summary": "x" * 50, "category": "x"},
        {"source": "A", "title": "two", "url": "https://a/2", "summary": "x" * 400, "category": "x"},
        {"source": "B", "title": "one", "url": "https://b/1", "summary": "", "category": "y"},
        {"source": "C", "title": "one", "url": "https://a/1", "summary": "x" * 50, "category": "z"},
    ]


def _make_config(feeds_overrides=None, global_overrides=None):
    feeds = [
        {"name": "A", "url": "https://a/", "category": "x"},
        {"name": "B", "url": "https://b/", "category": "y"},
        {"name": "C", "url": "https://c/", "category": "z"},
    ]
    if feeds_overrides:
        for feed in feeds:
            if feed["name"] in feeds_overrides:
                feed.update(feeds_overrides[feed["name"]])
    enrich = {
        "enabled": True,
        "threshold_chars": 200,
        "max_fetches_per_run": 40,
        "cache_ttl_days": 30,
        "cache_failure_backoff_hours": 24,
        "min_body_chars": 300,
        "timeout_seconds": 15,
        "impersonate": "chrome",
    }
    if global_overrides:
        enrich.update(global_overrides)
    return {"rss": {"feeds": feeds}, "enrich_articles": enrich}


class TestDedup:
    def test_preserves_first_occurrence(self):
        items = _make_rss_items()
        canonical_by_url, order = _dedup_by_url(items)
        assert canonical_by_url["https://a/1"] is items[0]
        assert canonical_by_url["https://a/2"] is items[1]
        assert canonical_by_url["https://b/1"] is items[2]
        assert len(canonical_by_url) == 3
        assert order == ["https://a/1", "https://a/2", "https://b/1"]


class TestShouldEnrich:
    def test_skip_true_returns_false_even_when_thin(self):
        item = {"summary": "", "url": "https://x/", "source": "A"}
        assert _should_enrich(item, {"enrich": {"skip": True}}, threshold=200) is False

    def test_fetch_article_true_returns_true_even_when_fat(self):
        item = {"summary": "x" * 500, "url": "https://x/", "source": "A"}
        assert _should_enrich(item, {"enrich": {"fetch_article": True}}, threshold=200) is True

    def test_thin_summary_triggers_enrichment(self):
        item = {"summary": "x" * 50, "url": "https://x/", "source": "A"}
        assert _should_enrich(item, {}, threshold=200) is True

    def test_fat_summary_does_not_trigger_enrichment(self):
        item = {"summary": "x" * 500, "url": "https://x/", "source": "A"}
        assert _should_enrich(item, {}, threshold=200) is False

    def test_missing_enrich_block_uses_threshold(self):
        item = {"summary": "x" * 50, "url": "https://x/", "source": "A"}
        assert _should_enrich(item, {"name": "A"}, threshold=200) is True


class TestRun:
    @patch("stages.enrich_articles._fetch_extract_distill")
    def test_enriches_thin_items_and_leaves_fat_items_alone(self, mock_pipeline, tmp_path):
        mock_pipeline.return_value = ("ENRICHED BODY", "ok", 200, 2000, "")
        context = {"raw_sources": {"rss": _make_rss_items()}}
        config = _make_config()
        config["_test_cache_dir"] = str(tmp_path / "article_bodies")
        config["_test_artifact_dir"] = str(tmp_path / "artifacts")

        out = run(context, config, model_config={"provider": "fireworks", "model": "x", "max_tokens": 500, "temperature": 0.2})
        items = out["raw_sources"]["rss"]

        # Item 0 (thin, url https://a/1) enriched
        assert items[0]["summary"] == "ENRICHED BODY"
        # Item 1 (fat, https://a/2) untouched
        assert items[1]["summary"] == "x" * 400
        # Item 2 (empty, https://b/1) enriched
        assert items[2]["summary"] == "ENRICHED BODY"
        # Item 3 (duplicate URL of item 0) backfilled from canonical
        assert items[3]["summary"] == "ENRICHED BODY"

    @patch("stages.enrich_articles._fetch_extract_distill")
    def test_skip_flag_bypasses_enrichment(self, mock_pipeline, tmp_path):
        mock_pipeline.return_value = ("ENRICHED BODY", "ok", 200, 2000, "")
        context = {"raw_sources": {"rss": _make_rss_items()}}
        config = _make_config(feeds_overrides={"A": {"enrich": {"skip": True}}})
        config["_test_cache_dir"] = str(tmp_path / "article_bodies")
        config["_test_artifact_dir"] = str(tmp_path / "artifacts")

        out = run(context, config, model_config={"provider": "fireworks", "model": "x", "max_tokens": 500, "temperature": 0.2})
        items = out["raw_sources"]["rss"]

        # A feed items unchanged (skip wins over thin)
        assert items[0]["summary"] == "x" * 50
        # B feed still enriched
        assert items[2]["summary"] == "ENRICHED BODY"

    @patch("stages.enrich_articles._fetch_extract_distill")
    def test_max_fetches_per_run_caps_work(self, mock_pipeline, tmp_path):
        mock_pipeline.return_value = ("ENRICHED", "ok", 200, 2000, "")
        # 50 thin items, cap at 10 fetches
        items = [
            {"source": "A", "title": f"t{i}", "url": f"https://a/{i}", "summary": "x" * 50, "category": "x"}
            for i in range(50)
        ]
        context = {"raw_sources": {"rss": items}}
        config = _make_config(global_overrides={"max_fetches_per_run": 10})
        config["_test_cache_dir"] = str(tmp_path / "article_bodies")
        config["_test_artifact_dir"] = str(tmp_path / "artifacts")

        run(context, config, model_config={"provider": "fireworks", "model": "x", "max_tokens": 500, "temperature": 0.2})
        assert mock_pipeline.call_count == 10

    @patch("stages.enrich_articles._fetch_extract_distill")
    def test_fetch_failure_leaves_original_summary(self, mock_pipeline, tmp_path):
        mock_pipeline.return_value = ("", "http_error", 500, 0, "boom")
        context = {"raw_sources": {"rss": _make_rss_items()}}
        config = _make_config()
        config["_test_cache_dir"] = str(tmp_path / "article_bodies")
        config["_test_artifact_dir"] = str(tmp_path / "artifacts")

        out = run(context, config, model_config={"provider": "fireworks", "model": "x", "max_tokens": 500, "temperature": 0.2})
        items = out["raw_sources"]["rss"]

        assert items[0]["summary"] == "x" * 50
        assert items[2]["summary"] == ""  # was empty, stays empty

    @patch("stages.enrich_articles._fetch_extract_distill")
    def test_disabled_flag_short_circuits(self, mock_pipeline, tmp_path):
        mock_pipeline.return_value = ("ENRICHED BODY", "ok", 200, 2000, "")
        context = {"raw_sources": {"rss": _make_rss_items()}}
        config = _make_config(global_overrides={"enabled": False})
        config["_test_cache_dir"] = str(tmp_path / "article_bodies")
        config["_test_artifact_dir"] = str(tmp_path / "artifacts")

        out = run(context, config, model_config={"provider": "fireworks", "model": "x", "max_tokens": 500, "temperature": 0.2})
        items = out["raw_sources"]["rss"]

        # Nothing enriched
        assert items[0]["summary"] == "x" * 50
        assert items[2]["summary"] == ""
        mock_pipeline.assert_not_called()
```

- [ ] **Step 7.2: Run tests to verify they fail**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_enrich_articles.py -v
```
Expected: `ModuleNotFoundError: stages.enrich_articles`.

- [ ] **Step 7.3: Implement `stages/enrich_articles.py`**

Create `stages/enrich_articles.py`:
```python
"""Stage: enrich_articles — fetch + extract + distill thin RSS items.

Inputs:  raw_sources (dict) from collect
Outputs: raw_sources (dict) with upgraded item["summary"] fields, plus
         an enrich_articles.json artifact listing per-item status.

Downstream stages are unaware of enrichment — a native-thick RSS
summary and a distilled article body both arrive as item["summary"].
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Optional

from morning_digest.llm import call_llm
from sources.article_cache import ArticleCache
from sources.article_extract import extract_article
from sources.article_fetch import fetch_article_html, load_cookies_file
from utils.prompts import load_prompt

log = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path(__file__).parent.parent / "cache" / "article_bodies"
_MAX_PARALLEL = 4


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    """Enrich qualifying RSS items with fetched article bodies."""
    raw_sources = deepcopy(context.get("raw_sources", {}))
    items = raw_sources.get("rss", []) or []

    enrich_cfg = config.get("enrich_articles", {}) or {}
    if not enrich_cfg.get("enabled", True) or not items:
        log.info("enrich_articles: disabled or no items")
        return {"raw_sources": raw_sources}

    feeds_by_name = {f["name"]: f for f in config.get("rss", {}).get("feeds", [])}

    cache_dir = Path(config.get("_test_cache_dir") or _DEFAULT_CACHE_DIR)
    cache = ArticleCache(
        cache_dir,
        ttl_days=enrich_cfg.get("cache_ttl_days", 30),
        failure_backoff_hours=enrich_cfg.get("cache_failure_backoff_hours", 24),
    )
    pruned = cache.prune()
    if pruned:
        log.info(f"enrich_articles: pruned {pruned} expired cache entries")

    threshold = enrich_cfg.get("threshold_chars", 200)
    max_fetches = enrich_cfg.get("max_fetches_per_run", 40)

    canonical_by_url, order = _dedup_by_url(items)

    targets: list[dict] = []
    for url in order:
        canonical = canonical_by_url[url]
        feed_conf = feeds_by_name.get(canonical.get("source"), {})
        if _should_enrich(canonical, feed_conf, threshold):
            targets.append(canonical)
            if len(targets) >= max_fetches:
                skipped = sum(1 for u in order if _should_enrich(canonical_by_url[u], feeds_by_name.get(canonical_by_url[u].get("source"), {}), threshold)) - max_fetches
                log.warning(f"enrich_articles: hit max_fetches_per_run={max_fetches}; ~{skipped} items left un-enriched")
                break

    status_records: list[dict] = []
    if targets:
        log.info(f"enrich_articles: enriching {len(targets)} of {len(order)} unique URLs")
        system_prompt = load_prompt("enrich_article_system.md")
        with ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as pool:
            futures = {
                pool.submit(
                    _enrich_one,
                    item,
                    feeds_by_name.get(item.get("source"), {}),
                    enrich_cfg,
                    cache,
                    system_prompt,
                    model_config,
                ): item for item in targets
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    record = future.result()
                except Exception as e:
                    log.error(f"enrich_articles: enrichment crashed for {item.get('url')}: {e}")
                    record = {
                        "url": item.get("url"),
                        "source": item.get("source"),
                        "status": "exception",
                        "error": str(e),
                    }
                status_records.append(record)

    # Backfill duplicates from the canonical twin.
    for item in items:
        canonical = canonical_by_url.get(item.get("url"))
        if canonical is not None and canonical is not item:
            item["summary"] = canonical["summary"]

    raw_sources["rss"] = items

    artifact_dir = Path(config.get("_test_artifact_dir")) if config.get("_test_artifact_dir") else None
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "enrich_articles.json").write_text(
            json.dumps({"records": status_records}, indent=2), encoding="utf-8"
        )

    return {"raw_sources": raw_sources, "enrich_articles": {"records": status_records}}


def _dedup_by_url(items: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """Return (canonical_by_url, order) — first-occurrence wins."""
    canonical: dict[str, dict] = {}
    order: list[str] = []
    for item in items:
        url = item.get("url")
        if not url or url in canonical:
            continue
        canonical[url] = item
        order.append(url)
    return canonical, order


def _should_enrich(item: dict, feed_conf: dict, threshold: int) -> bool:
    enrich = (feed_conf or {}).get("enrich", {}) or {}
    if enrich.get("skip", False):
        return False
    if enrich.get("fetch_article", False):
        return True
    return len(item.get("summary", "") or "") < threshold


def _enrich_one(
    item: dict,
    feed_conf: dict,
    enrich_cfg: dict,
    cache: ArticleCache,
    system_prompt: str,
    model_config: Optional[dict],
) -> dict:
    """Enrich a single item. Never raises — records failures in the cache."""
    url = item["url"]
    source = item.get("source", "")

    cached = cache.get(url)
    if cached is not None:
        if cached.status == "ok" and cached.compressed_body:
            item["summary"] = cached.compressed_body
        return {"url": url, "source": source, "status": f"cache_hit:{cached.status}", "error": ""}

    per_feed = (feed_conf or {}).get("enrich", {}) or {}
    impersonate = per_feed.get("impersonate") or enrich_cfg.get("impersonate", "chrome")
    timeout = per_feed.get("timeout_seconds") or enrich_cfg.get("timeout_seconds", 15)
    user_agent = per_feed.get("user_agent") or enrich_cfg.get("user_agent")
    cookies_path = per_feed.get("cookies_file")
    cookies_jar = load_cookies_file(cookies_path) if cookies_path else None
    min_body = per_feed.get("min_body_chars") or enrich_cfg.get("min_body_chars", 300)

    compressed, status, http_status, raw_length, error = _fetch_extract_distill(
        url=url,
        impersonate=impersonate,
        timeout=timeout,
        cookies=cookies_jar,
        user_agent=user_agent,
        min_body_chars=min_body,
        system_prompt=system_prompt,
        model_config=model_config,
    )

    cache.put(
        url=url,
        status=status,
        http_status=http_status,
        compressed_body=compressed,
        raw_length=raw_length,
        source_name=source,
        error=error,
    )
    if status == "ok" and compressed:
        item["summary"] = compressed
    return {"url": url, "source": source, "status": status, "http_status": http_status, "error": error}


def _fetch_extract_distill(
    url: str,
    impersonate: str,
    timeout: int,
    cookies,
    user_agent: Optional[str],
    min_body_chars: int,
    system_prompt: str,
    model_config: Optional[dict],
) -> tuple[str, str, Optional[int], int, str]:
    """Fetch -> extract -> distill. Returns (compressed, status, http_status, raw_length, error).

    status is one of: ok, http_error, extraction_failed, paywall, llm_failed.
    """
    fetched = fetch_article_html(
        url, impersonate=impersonate, timeout=timeout, cookies=cookies, user_agent=user_agent
    )
    if fetched.status != "ok":
        return "", fetched.status, fetched.http_status, 0, fetched.error

    extracted = extract_article(fetched.html, min_body_chars=min_body_chars)
    if extracted.status != "ok":
        return "", extracted.status, fetched.http_status, extracted.raw_length, ""

    if not model_config:
        # No LLM configured — fall back to a clamped raw body.
        return extracted.text[:2000], "llm_failed", fetched.http_status, extracted.raw_length, "no model_config"

    user_content = (
        f"Article URL: {url}\n"
        f"Article length: {extracted.raw_length} chars.\n"
        f"Target distillation: 300–500 words.\n\n"
        f"Article text:\n\n{extracted.text}"
    )
    try:
        compressed = call_llm(
            system_prompt,
            user_content,
            model_config,
            max_retries=2,
            json_mode=False,
            stream=False,
        )
    except Exception as e:
        return extracted.text[:2000], "llm_failed", fetched.http_status, extracted.raw_length, str(e)

    compressed = (compressed or "").strip()
    if not compressed:
        return extracted.text[:2000], "llm_failed", fetched.http_status, extracted.raw_length, "empty LLM response"
    return compressed, "ok", fetched.http_status, extracted.raw_length, ""
```

- [ ] **Step 7.4: Run tests to verify they pass**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_enrich_articles.py -v
```
Expected: all 11 tests pass.

- [ ] **Step 7.5: Run the full test suite to confirm no regressions**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/ -v
```
Expected: all green.

- [ ] **Step 7.6: Commit**

```bash
git add stages/enrich_articles.py tests/test_enrich_articles.py
git commit -m "Add enrich_articles pipeline stage

Fetches, extracts, and distills article bodies for RSS items whose
summary is below threshold (or whose feed opts in explicitly).
Downstream stages receive enriched content in item['summary'] — same
shape as native-thick RSS feeds — so no downstream code changes.
Never fails the pipeline: every failure path leaves the original
summary untouched. Dedups by URL before fetching; backfills duplicate
items from their canonical twin."
```

---

## Task 8: Register stage in `config.yaml`; add per-feed enrichment config

**Files:**
- Modify: `config.yaml`

- [ ] **Step 8.1: Add the `enrich_articles` stage to the pipeline manifest**

In `config.yaml`, in the `pipeline.stages` list, insert a new entry **between `collect` and `compress`** (the stage reads `raw_sources` and writes back the same shape, so the earliest slot is the right one):
```yaml
    - name: enrich_articles
      model:
        provider: fireworks
        model: "accounts/fireworks/models/minimax-m2p7"
        max_tokens: 500
        temperature: 0.2
```

- [ ] **Step 8.2: Add the global `enrich_articles:` block**

In `config.yaml`, add this top-level block (near `rss:` — before the `feeds` list is fine):
```yaml
enrich_articles:
  enabled: true
  threshold_chars: 200
  max_fetches_per_run: 40
  cache_ttl_days: 30
  cache_failure_backoff_hours: 24
  per_host_concurrency: 2
  per_host_min_interval_ms: 500
  min_body_chars: 300
  timeout_seconds: 15
  impersonate: "chrome"
```

- [ ] **Step 8.3: Add per-feed `enrich:` overrides for pre-seeded feeds**

Edit each of the feeds below in `config.yaml`. Use `replace_all: false` and match the whole existing line to replace.

**Hard paywalls — `skip: true`:**

- `Financial Times` — add `enrich: { skip: true }` inside the braces before the closing `}`.
- `The Economist (Finance & Economics)` — same.
- `Nikkei Asia` — same, with a comment `# re-evaluate after body-fallback fix shows real summaries`.
- `Nature` — same.
- `Science Magazine` — same.

Example for FT — before:
```yaml
    - { url: "https://www.ft.com/rss/home", name: "Financial Times", cap: 5, category: "econ-trade", reliability: "primary-reporting" }
```
After:
```yaml
    - { url: "https://www.ft.com/rss/home", name: "Financial Times", cap: 5, category: "econ-trade", reliability: "primary-reporting", enrich: { skip: true } }
```

Apply the same pattern for the other four feeds.

**Authenticated subscription — `cookies_file`:**

- `The Atlantic` — set `fetch_article: true` and `cookies_file: "cookies/atlantic.cookies.txt"`:

Before:
```yaml
    - { url: "https://www.theatlantic.com/feed/all/", name: "The Atlantic", cap: 8, category: "western-analysis", reliability: "analysis-opinion" }
```
After:
```yaml
    - { url: "https://www.theatlantic.com/feed/all/", name: "The Atlantic", cap: 8, category: "western-analysis", reliability: "analysis-opinion", enrich: { fetch_article: true, cookies_file: "cookies/atlantic.cookies.txt" } }
```

**html_index scrapers — opt-in to enrichment:**

- `Brad Setser` — add `enrich: { fetch_article: true }`.
- `China Global South Project` — same.
- `Reuters Markets` — same.
- `The Diff (Byrne Hobart)` — same.

Example for Brad Setser — before:
```yaml
    - { url: "https://www.cfr.org/series/follow-the-money", name: "Brad Setser", cap: 3, category: "econ-trade", reliability: "analysis-opinion", mode: "html_index" }
```
After:
```yaml
    - { url: "https://www.cfr.org/series/follow-the-money", name: "Brad Setser", cap: 3, category: "econ-trade", reliability: "analysis-opinion", mode: "html_index", enrich: { fetch_article: true } }
```

- [ ] **Step 8.4: Verify the config parses and the stage is registered**

```bash
docker compose run --rm --entrypoint "" morning-digest python -c "
import yaml
cfg = yaml.safe_load(open('/app/config.yaml'))
stages = [s['name'] for s in cfg['pipeline']['stages']]
assert 'enrich_articles' in stages, stages
i = stages.index('enrich_articles')
assert stages[i-1] == 'collect', (stages[i-1], 'expected collect before enrich_articles')
assert stages[i+1] == 'compress', (stages[i+1], 'expected compress after enrich_articles')
assert cfg['enrich_articles']['enabled'] is True
ft = [f for f in cfg['rss']['feeds'] if f['name'] == 'Financial Times'][0]
assert ft['enrich']['skip'] is True
atl = [f for f in cfg['rss']['feeds'] if f['name'] == 'The Atlantic'][0]
assert atl['enrich']['fetch_article'] is True
assert atl['enrich']['cookies_file'] == 'cookies/atlantic.cookies.txt'
setser = [f for f in cfg['rss']['feeds'] if f['name'] == 'Brad Setser'][0]
assert setser['enrich']['fetch_article'] is True
print('config ok')
"
```
Expected: `config ok`.

- [ ] **Step 8.5: Commit**

```bash
git add config.yaml
git commit -m "Register enrich_articles stage and pre-seed per-feed enrichment config

Adds the stage to the pipeline manifest between collect and compress,
the global enrich_articles block with sensible defaults, and per-feed
overrides: skip: true for hard paywalls (FT, Economist, Nikkei, Nature,
Science), fetch_article + cookies_file for The Atlantic, and
fetch_article: true for html_index scrapers (Brad Setser, China Global
South, Reuters Markets, The Diff)."
```

---

## Task 9: `scripts/audit_rss_quality.py` — audit tool

**Files:**
- Create: `scripts/audit_rss_quality.py`
- Create: `tests/test_audit_rss_quality.py`

- [ ] **Step 9.1: Write failing tests**

Create `tests/test_audit_rss_quality.py`:
```python
"""Tests for scripts.audit_rss_quality."""

import sys
import os
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.audit_rss_quality import (
    compute_feed_metrics,
    recommend_action,
    render_markdown_report,
    load_artifacts,
)


def _write_artifact(root, date_str, rss_items, enrich_records=None):
    d = root / date_str
    d.mkdir(parents=True, exist_ok=True)
    (d / "raw_sources.json").write_text(json.dumps({"rss": rss_items}))
    if enrich_records is not None:
        (d / "enrich_articles.json").write_text(json.dumps({"records": enrich_records}))


class TestComputeFeedMetrics:
    def test_counts_items_and_empty_rate(self):
        items = [
            {"source": "A", "summary": ""},
            {"source": "A", "summary": "x" * 100},
            {"source": "A", "summary": ""},
        ]
        m = compute_feed_metrics(items)["A"]
        assert m["items"] == 3
        assert m["empty_count"] == 2
        assert m["empty_rate"] == pytest.approx(2 / 3)

    def test_computes_median_length(self):
        items = [
            {"source": "A", "summary": "x" * 10},
            {"source": "A", "summary": "x" * 100},
            {"source": "A", "summary": "x" * 1000},
        ]
        m = compute_feed_metrics(items)["A"]
        assert m["median_chars"] == 100

    def test_separates_sources(self):
        items = [
            {"source": "A", "summary": "x" * 400},
            {"source": "B", "summary": ""},
        ]
        m = compute_feed_metrics(items)
        assert set(m.keys()) == {"A", "B"}
        assert m["B"]["empty_rate"] == 1.0


class TestRecommendAction:
    def test_high_paywall_rate_recommends_skip(self):
        rec = recommend_action(
            items=20, median_chars=40, empty_rate=0.0, paywall_rate=0.95, mode="rss", enrich_cfg={}
        )
        assert "skip" in rec

    def test_html_index_with_empty_summaries_recommends_fetch(self):
        rec = recommend_action(
            items=6, median_chars=0, empty_rate=1.0, paywall_rate=None, mode="html_index", enrich_cfg={}
        )
        assert "fetch_article" in rec

    def test_fat_summary_recommends_ok(self):
        rec = recommend_action(
            items=20, median_chars=400, empty_rate=0.0, paywall_rate=None, mode="rss", enrich_cfg={}
        )
        assert "ok" in rec.lower()

    def test_existing_opt_in_with_successful_enrichment_recommends_ok(self):
        rec = recommend_action(
            items=20,
            median_chars=50,
            empty_rate=0.0,
            paywall_rate=0.05,
            mode="rss",
            enrich_cfg={"fetch_article": True, "cookies_file": "x"},
        )
        assert "ok" in rec.lower()


class TestLoadArtifacts:
    def test_empty_root_returns_empty_list(self, tmp_path):
        assert load_artifacts(tmp_path, window_days=14) == []

    def test_loads_recent_artifacts(self, tmp_path):
        _write_artifact(tmp_path, "2026-04-18", [{"source": "A", "summary": "x"}])
        _write_artifact(tmp_path, "2026-04-19", [{"source": "B", "summary": ""}])
        loaded = load_artifacts(tmp_path, window_days=14)
        assert len(loaded) == 2


class TestRenderMarkdownReport:
    def test_renders_header_and_one_row_per_feed(self):
        metrics = {
            "A": {"items": 10, "median_chars": 40, "empty_rate": 0.1, "paywall_rate": 0.9,
                  "mode": "rss", "enrich_cfg": {}},
            "B": {"items": 5, "median_chars": 400, "empty_rate": 0.0, "paywall_rate": None,
                  "mode": "rss", "enrich_cfg": {}},
        }
        out = render_markdown_report(metrics)
        assert "| Feed" in out
        assert "| A |" in out
        assert "| B |" in out

    def test_empty_metrics_produces_stub_message(self):
        out = render_markdown_report({})
        assert "no" in out.lower() or "0 feeds" in out.lower()
```

- [ ] **Step 9.2: Run tests to verify they fail**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_audit_rss_quality.py -v
```
Expected: `ModuleNotFoundError: scripts.audit_rss_quality`.

- [ ] **Step 9.3: Implement `scripts/audit_rss_quality.py`**

Create `scripts/audit_rss_quality.py`:
```python
#!/usr/bin/env python3
"""Audit RSS feed quality across existing raw_sources artifacts.

Usage:
    python scripts/audit_rss_quality.py                    # last 14 days, stdout
    python scripts/audit_rss_quality.py --window 30        # last 30 days
    python scripts/audit_rss_quality.py --output output/audits/rss_quality_2026-04-19.md

Reads output/artifacts/*/raw_sources.json across a window, ranks feeds
by quality (lowest median summary length first), and prints a markdown
table with a Recommend column. When enrich_articles.json artifacts
exist in the same directories, paywall-fail and LLM-fallback rates
are also reported.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _ROOT / "output" / "artifacts"
_CONFIG_PATH = _ROOT / "config.yaml"


def load_artifacts(artifacts_root: Path, window_days: int) -> list[dict]:
    """Return a list of {"date", "rss_items", "enrich_records"} dicts for dated dirs within the window."""
    if not artifacts_root.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).date()
    out = []
    for d in sorted(p for p in artifacts_root.iterdir() if p.is_dir()):
        try:
            date = datetime.fromisoformat(d.name).date()
        except ValueError:
            continue
        if date < cutoff:
            continue
        raw = d / "raw_sources.json"
        if not raw.exists():
            continue
        try:
            rss_items = json.loads(raw.read_text(encoding="utf-8")).get("rss", []) or []
        except json.JSONDecodeError:
            continue
        enrich_records = []
        enrich_path = d / "enrich_articles.json"
        if enrich_path.exists():
            try:
                enrich_records = json.loads(enrich_path.read_text(encoding="utf-8")).get("records", []) or []
            except json.JSONDecodeError:
                pass
        out.append({"date": d.name, "rss_items": rss_items, "enrich_records": enrich_records})
    return out


def compute_feed_metrics(items: list[dict]) -> dict:
    """Return {source_name: {items, median_chars, empty_count, empty_rate, ...}}."""
    by_source: dict[str, list[int]] = defaultdict(list)
    empty_by_source: dict[str, int] = defaultdict(int)
    for it in items:
        src = it.get("source", "?")
        length = len(it.get("summary", "") or "")
        by_source[src].append(length)
        if length == 0:
            empty_by_source[src] += 1
    out = {}
    for src, lens in by_source.items():
        out[src] = {
            "items": len(lens),
            "median_chars": int(statistics.median(lens)) if lens else 0,
            "empty_count": empty_by_source[src],
            "empty_rate": empty_by_source[src] / len(lens) if lens else 0.0,
        }
    return out


def merge_enrich_metrics(feed_metrics: dict, enrich_records: list[dict]) -> None:
    """Add paywall_rate and llm_fallback_rate to feed_metrics in-place."""
    by_source_status: dict[str, list[str]] = defaultdict(list)
    for rec in enrich_records:
        src = rec.get("source", "?")
        by_source_status[src].append(rec.get("status", ""))
    for src, statuses in by_source_status.items():
        if src not in feed_metrics:
            continue
        n = len(statuses)
        paywall = sum(1 for s in statuses if s == "paywall" or s == "http_error")
        llm_failed = sum(1 for s in statuses if s == "llm_failed")
        feed_metrics[src]["paywall_rate"] = paywall / n if n else None
        feed_metrics[src]["llm_fallback_rate"] = llm_failed / n if n else None
    for src, m in feed_metrics.items():
        m.setdefault("paywall_rate", None)
        m.setdefault("llm_fallback_rate", None)


def annotate_with_config(feed_metrics: dict, config_path: Path) -> None:
    """Add mode and enrich_cfg per feed from config.yaml."""
    if not config_path.exists():
        return
    try:
        import yaml
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return
    feeds_by_name = {f["name"]: f for f in config.get("rss", {}).get("feeds", []) or []}
    for src, m in feed_metrics.items():
        f = feeds_by_name.get(src, {})
        m["mode"] = f.get("mode", "rss")
        m["enrich_cfg"] = f.get("enrich", {}) or {}


def recommend_action(
    items: int,
    median_chars: int,
    empty_rate: float,
    paywall_rate: float | None,
    mode: str,
    enrich_cfg: dict,
) -> str:
    already_opted_in = enrich_cfg.get("fetch_article", False)
    already_skipping = enrich_cfg.get("skip", False)
    has_cookies = bool(enrich_cfg.get("cookies_file"))

    if paywall_rate is not None and paywall_rate >= 0.8:
        if has_cookies:
            return "refresh cookies (paywall rate high)"
        if already_opted_in:
            return "skip: true (paywall consumes budget)"
        return "skip: true"

    if already_opted_in and paywall_rate is not None and paywall_rate < 0.3:
        return "ok (enrichment working)"

    if already_skipping:
        return "ok (intentionally skipped)"

    if median_chars == 0 and mode == "html_index":
        return "fetch_article: true"

    if median_chars < 200:
        return "fetch_article: true"

    return "ok"


def render_markdown_report(feed_metrics: dict) -> str:
    if not feed_metrics:
        return "# RSS Feed Quality Audit\n\nNo feeds found in window. No artifacts matched.\n"

    rows = []
    for src, m in feed_metrics.items():
        rec = recommend_action(
            items=m["items"],
            median_chars=m["median_chars"],
            empty_rate=m["empty_rate"],
            paywall_rate=m.get("paywall_rate"),
            mode=m.get("mode", "rss"),
            enrich_cfg=m.get("enrich_cfg", {}),
        )
        rows.append((m["median_chars"], src, m["items"], m["empty_rate"], m.get("paywall_rate"), m.get("mode", "rss"), rec))
    rows.sort(key=lambda r: (r[0], r[1]))  # worst median first

    lines = ["# RSS Feed Quality Audit", ""]
    lines.append("| Feed | Items | Median chars | Empty % | Paywall % | Mode | Recommend |")
    lines.append("|---|---:|---:|---:|---:|---|---|")
    for median, src, n, empty, paywall, mode, rec in rows:
        paywall_col = f"{int(paywall * 100)}%" if paywall is not None else "—"
        lines.append(f"| {src} | {n} | {median} | {int(empty * 100)}% | {paywall_col} | {mode} | {rec} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Audit RSS feed quality.")
    parser.add_argument("--window", type=int, default=14, help="Days of artifacts to consider (default 14)")
    parser.add_argument("--output", type=str, default=None, help="Write report to this path instead of stdout")
    parser.add_argument("--artifacts-dir", type=str, default=str(_ARTIFACTS_DIR))
    parser.add_argument("--config", type=str, default=str(_CONFIG_PATH))
    args = parser.parse_args()

    artifacts = load_artifacts(Path(args.artifacts_dir), window_days=args.window)
    if not artifacts:
        report = "# RSS Feed Quality Audit\n\nNo artifact directories found under output/artifacts/.\nRun the pipeline at least once, then re-run this audit.\n"
    else:
        all_items = []
        all_enrich = []
        for a in artifacts:
            all_items.extend(a["rss_items"])
            all_enrich.extend(a["enrich_records"])
        feed_metrics = compute_feed_metrics(all_items)
        merge_enrich_metrics(feed_metrics, all_enrich)
        annotate_with_config(feed_metrics, Path(args.config))
        report = render_markdown_report(feed_metrics)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"Report written to {out}")
    else:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
```

- [ ] **Step 9.4: Run tests to verify they pass**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_audit_rss_quality.py -v
```
Expected: all 11 tests pass.

- [ ] **Step 9.5: Run the audit tool against real artifacts**

```bash
docker compose run --rm --entrypoint "" morning-digest python scripts/audit_rss_quality.py --window 14
```
Expected: a markdown table ranked by median summary length, worst first. Entries like Brad Setser (0) and China Global South (0) at the top. FT, Nikkei, etc. with their recommended actions. No errors.

- [ ] **Step 9.6: Commit and push batch so far**

```bash
git add scripts/audit_rss_quality.py tests/test_audit_rss_quality.py
git commit -m "Add RSS feed quality audit tool

Reads output/artifacts/*/raw_sources.json and optional
enrich_articles.json across a configurable window (default 14 days),
ranks feeds by median summary length, and recommends per-feed
actions (fetch_article, skip, cookies refresh, ok). Graceful on
empty input: reports a no-artifacts notice rather than crashing."

git push
```

---

## Task 10: Docker mount for cookies + gitignore

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.gitignore`
- Create: `.dockerignore` (if missing)

- [ ] **Step 10.1: Create the cookies directory stub**

```bash
cd /home/aaron/Morning-Digest
mkdir -p cookies
touch cookies/.gitkeep
```

The `.gitkeep` ensures the directory exists when the repo is cloned. Cookie files are gitignored.

- [ ] **Step 10.2: Add `cookies/` mount to `docker-compose.yml`**

In `docker-compose.yml`, in the `volumes:` block, add this line after the existing `config.yaml` mount:
```yaml
      - ./cookies:/app/cookies:ro
```

Final `volumes:` section should read:
```yaml
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ./cookies:/app/cookies:ro
      - ./output:/app/output
      - ./tests:/app/tests:ro
```

- [ ] **Step 10.3: Add `cookies/*` to `.gitignore` (but keep `.gitkeep`)**

Append to `.gitignore`:
```
# Authenticated-fetch cookie files (never commit)
cookies/*
!cookies/.gitkeep
```

- [ ] **Step 10.4: Check `.dockerignore` — create if missing**

```bash
ls /home/aaron/Morning-Digest/.dockerignore 2>/dev/null || echo "missing"
```

If it prints `missing`, create `.dockerignore` with:
```
__pycache__
*.pyc
.git
.venv
venv
output/artifacts/*
output/audits/*
cookies/*
!cookies/.gitkeep
.env
```

If it exists, append these two lines (skip duplicates):
```
cookies/*
!cookies/.gitkeep
```

- [ ] **Step 10.5: Rebuild and verify the mount works**

```bash
cd /home/aaron/Morning-Digest
docker compose build
docker compose run --rm --entrypoint "" morning-digest ls /app/cookies
```
Expected: lists `.gitkeep`. No errors.

- [ ] **Step 10.6: Commit**

```bash
git add docker-compose.yml .gitignore .dockerignore cookies/.gitkeep
git commit -m "Mount cookies/ read-only in Docker, gitignore cookie files

Cookie files for authenticated fetches (currently The Atlantic) live
in cookies/ at the project root and are bind-mounted read-only into
the container — same convention used for config.yaml. The directory
itself is tracked via .gitkeep, contents are gitignored and
dockerignored to avoid committing session tokens."
```

---

## Task 11: Prompt updates — enrichment context note

**Files:**
- Modify: `prompts/analyze_domain_system.md`
- Modify: `prompts/seam_candidates.md`
- Modify: `prompts/seam_annotations.md`
- Modify: `prompts/cross_domain_plan.md`
- Modify: `prompts/cross_domain_execute.md`
- Modify: `prompts/cross_domain_system.md` (if exists)

- [ ] **Step 11.1: Prepare the note text**

The canonical note (identical in every prompt):
```
Note on source material: Some item summaries include extracted article body text, not just the RSS description. Article bodies may have been captured up to 30 days ago (on the day the URL was first seen) rather than fetched fresh today; prefer analysis grounded in items from the most recent 24–48 hours but don't ignore context from older captures when it clarifies a current story.
```

- [ ] **Step 11.2: Add the note to `prompts/analyze_domain_system.md`**

Open the file. Find the first occurrence of `source` or `item` in the body (where source materials are introduced). Insert the note as a new paragraph in the most natural location — typically right before the task instructions. If unsure, append as the final paragraph before the output-format instructions.

Verify:
```bash
grep -c "Article bodies may have been captured" prompts/analyze_domain_system.md
```
Expected: `1`.

- [ ] **Step 11.3: Add the note to `prompts/seam_candidates.md` and `prompts/seam_annotations.md`**

Same pattern — insert as a paragraph near where source material is introduced. Verify each:
```bash
grep -c "Article bodies may have been captured" prompts/seam_candidates.md
grep -c "Article bodies may have been captured" prompts/seam_annotations.md
```
Both expected `1`.

- [ ] **Step 11.4: Add the note to `prompts/cross_domain_plan.md` and `prompts/cross_domain_execute.md`**

Same pattern. Verify:
```bash
grep -c "Article bodies may have been captured" prompts/cross_domain_plan.md
grep -c "Article bodies may have been captured" prompts/cross_domain_execute.md
```
Both expected `1`.

- [ ] **Step 11.5: Handle `cross_domain_system.md` if present**

```bash
ls prompts/cross_domain_system.md 2>/dev/null && echo "exists" || echo "absent"
```
If it exists, add the note and verify with grep. If absent, skip.

- [ ] **Step 11.6: Run the prompts test to confirm the files still load**

```bash
docker compose run --rm --entrypoint "" morning-digest pytest tests/test_prompts.py -v
```
Expected: pass. If any test enforces an exact prompt length or hash, update it to reflect the additions.

- [ ] **Step 11.7: Commit**

```bash
git add prompts/analyze_domain_system.md prompts/seam_candidates.md prompts/seam_annotations.md prompts/cross_domain_plan.md prompts/cross_domain_execute.md
# Only include cross_domain_system.md if it exists and was edited.
git commit -m "Note enrichment context in analysis prompts

Downstream prompts now mention that some item summaries include
extracted article body text (possibly captured up to 30 days ago)
rather than live RSS descriptions. Prompts still prefer recent
items; the note just prevents the model from assuming every summary
is a fresh RSS blurb."
```

---

## Task 12: Documentation updates — README and CLAUDE.md

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 12.1: Add `enrich_articles` bullet to README pipeline stages list**

In `README.md`, find the `- **collect**` bullet under the "Processes sources through a staged AI pipeline" numbered item. Insert a new bullet immediately after it, before `- **compress**`:

Before:
```markdown
   - **collect** — Fetches raw sources in parallel...
   - **compress** — Pre-compresses YouTube transcripts to ~400–800 word summaries
```

After:
```markdown
   - **collect** — Fetches raw sources in parallel...
   - **enrich_articles** — For RSS items with thin/empty summaries, fetches the article URL via curl-cffi (Chrome TLS fingerprint), extracts the body with trafilatura, and distills to 300–500 words via a cheap LLM pass. 30-day disk cache; per-run fetch cap; per-feed opt-in or skip via config.yaml. Authenticated subscriptions supported via Netscape cookies.txt.
   - **compress** — Pre-compresses YouTube transcripts to ~400–800 word summaries
```

If the collect bullet text in the current README differs, keep its original text intact and only insert the new `enrich_articles` line between it and `compress`.

- [ ] **Step 12.2: Add `enrich_articles` to the Pipeline Flow mermaid diagram**

Find the mermaid diagram in README (begins with `graph TD` under "Pipeline Flow"). Insert `enrich_articles` between `collect` and `compress`.

Before:
```
    collect --> compress
    compress --> analyze_domain
```

After:
```
    collect --> enrich_articles
    enrich_articles --> compress
    compress --> analyze_domain
```

- [ ] **Step 12.3: Add an "Article enrichment" subsection**

Insert after the existing "Configuration" section (or near the RSS config docs — pick a location consistent with the existing structure).

Template:
````markdown
### Article enrichment

Some RSS feeds arrive with empty or too-short summaries — index-page scrapers (e.g. Brad Setser, Reuters Markets) and a handful of outlets that publish headline-only RSS (FT, Atlantic teaser, several Substacks). The `enrich_articles` stage fetches the article URL, extracts the body with trafilatura, and distills it to 300–500 words so downstream analysis has real substance instead of a title.

**Global config** (`config.yaml`):
```yaml
enrich_articles:
  enabled: true
  threshold_chars: 200         # any item with summary shorter than this gets fetched
  max_fetches_per_run: 40      # hard ceiling per pipeline run
  cache_ttl_days: 30           # reuse prior fetches for 30 days
  cache_failure_backoff_hours: 24
  min_body_chars: 300          # shorter than this after extraction = treated as failure
  timeout_seconds: 15
  impersonate: "chrome"        # curl-cffi browser profile
```

**Per-feed overrides** (add an `enrich:` sub-block to any feed in `rss.feeds`):
```yaml
enrich:
  fetch_article: true          # always fetch this feed's items
  skip: true                   # never enrich this feed (e.g. hard paywalls)
  cookies_file: "cookies/atlantic.cookies.txt"  # Netscape cookies.txt for auth
  min_body_chars: 500          # override global minimum
  timeout_seconds: 30          # override global timeout
  user_agent: "..."            # override default Chrome UA (rare)
  impersonate: "firefox"       # override browser profile (rare)
```

Cached article bodies live in `cache/article_bodies/` (one JSON per URL, keyed by SHA-1). Pruning runs at the top of every stage invocation.

### Authenticated fetches

Subscription sites require browser cookies for real article access. Cookies live in `cookies/` at the project root (gitignored, mounted read-only into the container — same pattern as `config.yaml`).

**Exporting cookies:**
1. Install the "Get cookies.txt LOCALLY" browser extension (Chrome or Firefox).
2. Log into the subscription site in that browser.
3. **Filter the export to the single target domain** — the extension defaults to the full browser jar (thousands of unrelated cookies). Use the domain filter / "Current Site" option so the exported file contains only cookies for e.g. `theatlantic.com`. A full-jar export works functionally but dramatically increases the blast radius if the file or container is ever compromised.
4. Save as `cookies/<name>.cookies.txt` at the project root.
5. Reference the path from the feed's `enrich.cookies_file` setting.

Cookies expire periodically. When `output/artifacts/{date}/enrich_articles.json` shows `paywall` status for the feed's URLs, re-export and overwrite.
````

- [ ] **Step 12.4: Add a "Diagnostics" subsection**

Insert right after the "Article enrichment" subsection:

````markdown
### Diagnostics: RSS feed quality audit

The audit tool ranks feeds by summary quality so you can identify which ones need enrichment opt-ins, which paywalls should be skipped, and when cookies need refreshing.

```bash
# Last 14 days of artifacts, to stdout
docker compose run --rm --entrypoint "" morning-digest python scripts/audit_rss_quality.py

# Longer window, write to file
docker compose run --rm --entrypoint "" morning-digest \
  python scripts/audit_rss_quality.py --window 30 --output output/audits/rss_quality_$(date -u +%F).md
```

The report's `Recommend` column suggests actions:
- `fetch_article: true` — thin/empty summaries, worth enriching
- `skip: true` — high paywall-fail rate; fetches waste budget
- `refresh cookies (paywall rate high)` — cookies likely expired
- `ok (enrichment working)` — current config is doing its job
- `ok (intentionally skipped)` — feed is paywalled and explicitly skipped

Workflow: audit → update `config.yaml` per recommendations → wait 3–5 runs → re-audit → iterate.
````

- [ ] **Step 12.5: Update the dependencies note in README install section**

Find the install instructions (or `requirements.txt` mention). Add a brief line:

```markdown
Enrichment dependencies: `trafilatura` (article body extraction) and `curl-cffi` (Chrome TLS fingerprinting for fetches that need to look like a real browser). Both install from PyPI wheels — no extra system packages.
```

- [ ] **Step 12.6: Add enrichment pointers to `CLAUDE.md`**

Append a new section at the end of `CLAUDE.md`:
```markdown
## Article enrichment

- The `enrich_articles` stage runs between `collect` and `compress`. Its artifact is `output/artifacts/{date}/enrich_articles.json` — per-item fetch/extraction/distillation status is recorded there.
- The canonical way to measure RSS feed quality is `scripts/audit_rss_quality.py`. Run it manually; do not bake it into the pipeline.
- Cookie files for authenticated fetches live in `cookies/` (gitignored). Refresh when the audit tool flags `paywall` rate rising for a feed that should have working cookies.
```

- [ ] **Step 12.7: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "Document article enrichment, cookies workflow, audit tool

README gains: enrich_articles bullet in the stage list and mermaid
diagram; Article enrichment subsection with global/per-feed config;
Authenticated fetches subsection walking through cookies.txt export;
Diagnostics subsection for the audit tool. CLAUDE.md gets a short
pointer to the stage artifact and audit script."
```

---

## Task 13: End-to-end verification

**Files:** none (verification only).

- [ ] **Step 13.1: Full test suite**

```bash
cd /home/aaron/Morning-Digest
docker compose run --rm --entrypoint "" morning-digest pytest tests/ -v
```
Expected: all green.

- [ ] **Step 13.2: Dry-run the pipeline**

```bash
docker compose run --rm --entrypoint "" morning-digest python pipeline.py --dry-run
```
Expected: full pipeline runs end-to-end. `enrich_articles` stage executes with log lines like `enrich_articles: enriching N of M unique URLs`. No stage errors. Email is not sent (`--dry-run`).

- [ ] **Step 13.3: Inspect the enrichment artifact**

```bash
ls output/artifacts/$(date -u +%F)/enrich_articles.json
docker compose run --rm --entrypoint "" morning-digest python - <<'PY'
import json, pathlib
from collections import Counter
path = sorted(pathlib.Path("output/artifacts").iterdir())[-1] / "enrich_articles.json"
records = json.loads(path.read_text())["records"]
print(f"{len(records)} enrichment attempts")
print(Counter(r["status"] for r in records).most_common())
PY
```
Expected: a populated artifact; distribution of statuses includes `ok` (or `cache_hit:ok`) for opt-in feeds and `paywall` for FT etc. No crashes.

- [ ] **Step 13.4: Run the audit tool against the fresh run**

```bash
docker compose run --rm --entrypoint "" morning-digest python scripts/audit_rss_quality.py --window 1
```
Expected: report includes paywall-rate and LLM-fallback columns populated from the enrichment artifact. Brad Setser / China Global South show non-zero median characters (enrichment worked). FT shows high paywall rate with `skip: true` recommendation (already applied — should read "ok (intentionally skipped)").

- [ ] **Step 13.5: Push the final batch**

```bash
git push
```

- [ ] **Step 13.6: Report back to the user**

Summarize: tasks completed, any items from Task 0 that required adjustments, enrichment artifact counts from the first real run, and whether the audit tool output matches expectations. Flag anything that needs follow-up (e.g. cookies not yet exported for The Atlantic — `skip: true` on a paywall-heavy feed that should be opted-in with cookies, etc.).

No commit for this task.

---
