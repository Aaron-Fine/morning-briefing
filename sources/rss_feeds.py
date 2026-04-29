"""Fetch and aggregate RSS feeds — direct or via FreshRSS API."""

import json
import logging
import signal
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from dateutil import parser as dateparser

log = logging.getLogger(__name__)

_MAX_PARALLEL_FEED_FETCHES = 6
_FETCH_STATE_PATH = Path(__file__).parent.parent / "cache" / "rss_fetch_state.json"
_USER_AGENT = "MorningDigest/1.0 (morningDigest@lurkers.us)"
_DEFAULT_429_COOLDOWN_SECONDS = 6 * 60 * 60
_DEFAULT_BROKEN_FEED_COOLDOWN_SECONDS = 24 * 60 * 60
_PERSISTENT_ERROR_STATUSES = {400, 401, 404, 410}
_HTML_INDEX_IGNORE_TITLES = {
    "home",
    "latest",
    "archive",
    "subscribe",
    "sign in",
    "log in",
    "login",
    "read more",
    "view all",
    "all posts",
    "news feed",
}
_HTML_INDEX_IGNORE_PATH_PARTS = (
    "/feed",
    "/tag/",
    "/topics/",
    "/author/",
    "/authors/",
    "/category/",
    "/subscribe",
    "/account",
    "/search",
    "/about",
)


def fetch_rss(config: dict) -> list[dict]:
    """Return recent RSS items from configured feeds.
    
    Returns list of dicts: {source, title, url, published, summary}
    """
    items, _diagnostics = fetch_rss_with_diagnostics(config)
    return items


def fetch_rss_with_diagnostics(config: dict) -> tuple[list[dict], list[dict]]:
    """Return RSS items plus per-feed collection diagnostics."""
    rss_config = config.get("rss", {})
    provider = rss_config.get("provider", "direct")

    if provider == "freshrss" and rss_config.get("freshrss_url"):
        # FreshRSS is aggregate-oriented; direct per-feed diagnostics are unavailable.
        items = _fetch_from_freshrss(rss_config)
        return items, [
            {
                "source": "FreshRSS",
                "url": rss_config.get("freshrss_url", ""),
                "mode": "freshrss",
                "status": "ok" if items else "empty",
                "item_count": len(items),
                "error": "",
            }
        ]
    result = _fetch_direct(rss_config, include_diagnostics=True)
    if isinstance(result, tuple):
        return result
    return result, []


class _FeedParseTimeout(Exception):
    pass


class _AnchorParser(HTMLParser):
    """Collect anchor href/text pairs from simple article index pages."""

    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text = " ".join("".join(self._parts).split())
        self.links.append((self._href, text))
        self._href = None
        self._parts = []


def _parse_feed_with_timeout(content: bytes, feed_name: str, timeout_secs: int = 10):
    """Parse feed content with a SIGALRM timeout guard.

    feedparser.parse() has no built-in timeout and can hang on deeply nested
    or malformed XML content.
    """
    def _handler(signum, frame):
        raise _FeedParseTimeout(f"feedparser.parse() timed out for {feed_name}")

    prev_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout_secs)
    try:
        return feedparser.parse(content)
    except _FeedParseTimeout:
        log.warning(f"Feed parse timed out for {feed_name} (>{timeout_secs}s)")
        return feedparser.FeedParserDict(entries=[])
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev_handler)


def _fetch_direct(
    rss_config: dict,
    include_diagnostics: bool = False,
) -> list[dict] | tuple[list[dict], list[dict]]:
    """Fetch from individual RSS feed URLs."""
    feeds = rss_config.get("feeds", [])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    all_items = []
    diagnostics = []
    consecutive_failures = 0
    fetch_state = _load_fetch_state()
    state_changed = False

    for start in range(0, len(feeds), _MAX_PARALLEL_FEED_FETCHES):
        batch = feeds[start:start + _MAX_PARALLEL_FEED_FETCHES]
        batch_results = _fetch_feed_batch(batch, fetch_state)

        for feed_conf, fetch_result in zip(batch, batch_results):
            if consecutive_failures >= 5:
                remaining = len(feeds) - feeds.index(feed_conf)
                log.warning(
                    f"RSS: {consecutive_failures} consecutive fetch failures — "
                    f"network likely down, skipping remaining {remaining} feeds"
                )
                break

            if fetch_result.get("skipped"):
                diagnostics.append(
                    _feed_diagnostic(feed_conf, fetch_result, "skipped_cooldown", 0)
                )
                continue

            _apply_fetch_state(feed_conf, fetch_result, fetch_state)
            state_changed = True

            feed_content = fetch_result.get("content")
            if feed_content is None:
                consecutive_failures += 1
                diagnostics.append(
                    _feed_diagnostic(feed_conf, fetch_result, "http_error", 0)
                )
                continue

            consecutive_failures = 0
            try:
                items = _extract_feed_items(
                    feed_conf,
                    feed_content,
                    fetch_result.get("content_type", ""),
                    cutoff,
                )
                all_items.extend(items)
                diagnostics.append(
                    _feed_diagnostic(
                        feed_conf,
                        fetch_result,
                        "ok" if items else "empty",
                        len(items),
                    )
                )
            except Exception as e:
                error = str(e)
                log.warning(f"RSS parse failed for {feed_conf['name']}: {error}")
                fetch_result["error"] = error
                diagnostics.append(
                    _feed_diagnostic(feed_conf, fetch_result, "parse_error", 0)
                )
        else:
            continue
        break

    if state_changed:
        _save_fetch_state(fetch_state)

    if all_items:
        log.info(f"RSS: fetched {len(all_items)} items from {len(feeds)} feeds")
    else:
        log.warning("RSS: no items fetched from any feed")
    all_items.sort(key=lambda x: x.get("published", ""), reverse=True)
    if include_diagnostics:
        return all_items, diagnostics
    return all_items


def _feed_diagnostic(
    feed_conf: dict,
    fetch_result: dict,
    status: str,
    item_count: int,
) -> dict:
    return {
        "source": feed_conf.get("name", ""),
        "url": feed_conf.get("url", ""),
        "mode": feed_conf.get("mode", "rss"),
        "cap": feed_conf.get("cap", ""),
        "status": status,
        "status_code": fetch_result.get("status_code"),
        "item_count": item_count,
        "content_type": fetch_result.get("content_type", ""),
        "error": fetch_result.get("error", ""),
        "skipped": bool(fetch_result.get("skipped", False)),
    }


def _fetch_feed_batch(feeds: list[dict], fetch_state: dict) -> list[dict]:
    """Fetch one batch of feed bytes in parallel, preserving input order."""
    active_feeds: list[dict] = []
    results_by_key: dict[str, dict] = {}

    for feed_conf in feeds:
        skipped = _skip_due_to_cooldown(feed_conf, fetch_state)
        if skipped is not None:
            results_by_key[_state_key(feed_conf)] = skipped
        else:
            active_feeds.append(feed_conf)

    max_workers = min(_MAX_PARALLEL_FEED_FETCHES, len(active_feeds) or 1)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fetched = list(pool.map(_fetch_feed_content, active_feeds))

    for feed_conf, result in zip(active_feeds, fetched):
        results_by_key[_state_key(feed_conf)] = result

    return [results_by_key[_state_key(feed_conf)] for feed_conf in feeds]


def _fetch_feed_content(feed_conf: dict) -> dict:
    """Fetch raw feed bytes or HTML index content for one configured source."""
    try:
        resp = requests.get(
            feed_conf["url"],
            headers=_request_headers(feed_conf),
            timeout=15,
        )
        resp.raise_for_status()
        return {
            "content": resp.content,
            "content_type": resp.headers.get("Content-Type", ""),
            "status_code": resp.status_code,
            "error": "",
            "skipped": False,
        }
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        error = str(e)
    except Exception as e:
        status_code = None
        error = str(e)

    label = f"RSS {feed_conf['name']}"
    if status_code is None:
        log.warning(f"{label}: HTTP GET failed: {error}")
    else:
        log.warning(f"{label}: HTTP GET failed: {error}")
    return {
        "content": None,
        "content_type": "",
        "status_code": status_code,
        "error": error,
        "skipped": False,
    }


def _request_headers(feed_conf: dict) -> dict:
    headers = {"User-Agent": _USER_AGENT}
    if feed_conf.get("mode") == "html_index":
        headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            }
        )
    return headers


def _load_fetch_state() -> dict:
    if not _FETCH_STATE_PATH.exists():
        return {}
    try:
        return json.loads(_FETCH_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_fetch_state(fetch_state: dict) -> None:
    _FETCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FETCH_STATE_PATH.write_text(
        json.dumps(fetch_state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _state_key(feed_conf: dict) -> str:
    return f"{feed_conf.get('name', '')}|{feed_conf.get('url', '')}"


def _skip_due_to_cooldown(feed_conf: dict, fetch_state: dict) -> dict | None:
    state = fetch_state.get(_state_key(feed_conf))
    if state is None:
        # Backward-compatible read for state files created before URL-stable keys.
        state = fetch_state.get(feed_conf.get("name", ""), {})
    cooldown_until = state.get("cooldown_until", 0)
    now_ts = datetime.now(timezone.utc).timestamp()
    if cooldown_until <= now_ts:
        return None

    retry_at = datetime.fromtimestamp(cooldown_until, tz=timezone.utc).isoformat()
    log.info(
        f"RSS {feed_conf['name']}: skipping fetch until {retry_at} after recent "
        f"HTTP {state.get('last_status', '?')}"
    )
    return {
        "content": None,
        "content_type": "",
        "status_code": state.get("last_status"),
        "error": state.get("last_error", ""),
        "skipped": True,
    }


def _apply_fetch_state(feed_conf: dict, fetch_result: dict, fetch_state: dict) -> None:
    key = _state_key(feed_conf)
    state = dict(fetch_state.get(key, {}))
    state["last_checked"] = datetime.now(timezone.utc).isoformat()
    state["last_status"] = fetch_result.get("status_code")
    state["last_error"] = fetch_result.get("error", "")

    status_code = fetch_result.get("status_code")
    if fetch_result.get("content") is not None:
        state["cooldown_until"] = 0
        state["last_success"] = state["last_checked"]
    elif status_code == 429:
        cooldown = feed_conf.get(
            "cooldown_on_429_seconds", _DEFAULT_429_COOLDOWN_SECONDS
        )
        state["cooldown_until"] = (
            datetime.now(timezone.utc).timestamp() + cooldown
        )
    elif status_code in _PERSISTENT_ERROR_STATUSES:
        cooldown = feed_conf.get(
            "cooldown_on_error_seconds", _DEFAULT_BROKEN_FEED_COOLDOWN_SECONDS
        )
        state["cooldown_until"] = (
            datetime.now(timezone.utc).timestamp() + cooldown
        )
    else:
        state["cooldown_until"] = 0

    fetch_state[key] = state


def _extract_feed_items(
    feed_conf: dict,
    content: bytes,
    content_type: str,
    cutoff: datetime,
) -> list[dict]:
    if feed_conf.get("mode") != "html_index":
        parsed = _parse_feed_with_timeout(content, feed_conf["name"])
        if parsed.entries:
            return _items_from_parsed_feed(feed_conf, parsed.entries, cutoff)

    if feed_conf.get("mode") == "html_index" or "html" in content_type.lower():
        html_items = _items_from_html_index(feed_conf, content)
        if html_items:
            return html_items

    return []


def _items_from_parsed_feed(
    feed_conf: dict,
    entries: list,
    cutoff: datetime,
) -> list[dict]:
    items = []
    cap = feed_conf.get("cap", 15)
    tag = feed_conf.get("tag", "")
    category = feed_conf.get("category", "")

    for entry in entries:
        published = _parse_feed_date(entry)
        if published and published < cutoff:
            continue

        item = {
            "source": feed_conf["name"],
            "title": entry.get("title", "").strip(),
            "url": entry.get("link", ""),
            "published": published.isoformat() if published else "",
            "summary": _clean_summary(_entry_body(entry)),
        }
        native_body = _entry_body(entry)
        if native_body:
            item["_rss_body"] = native_body
        _copy_feed_metadata(item, feed_conf, tag, category)
        items.append(item)
        if len(items) >= cap:
            break

    return items


def _entry_body(entry) -> str:
    """Return the first non-empty body-like field from a feedparser entry."""
    candidates: list[str] = []
    content = entry.get("content") or []
    if content:
        for part in content:
            if isinstance(part, dict):
                candidates.append(part.get("value", "") or "")

    candidates.extend(
        [
            entry.get("summary", "") or "",
            entry.get("description", "") or "",
        ]
    )

    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate
    return ""


def _items_from_html_index(feed_conf: dict, content: bytes) -> list[dict]:
    parser = _AnchorParser()
    parser.feed(content.decode("utf-8", errors="ignore"))

    base_url = feed_conf["url"]
    base_netloc = urlparse(base_url).netloc
    tag = feed_conf.get("tag", "")
    category = feed_conf.get("category", "")
    cap = feed_conf.get("cap", 15)
    fetched_at = datetime.now(timezone.utc).isoformat()
    items = []
    seen_urls: set[str] = set()

    for href, title in parser.links:
        if not _looks_like_article_link(base_netloc, href, title):
            continue
        absolute_url = urljoin(base_url, href)
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)

        item = {
            "source": feed_conf["name"],
            "title": title.strip(),
            "url": absolute_url,
            "published": "",
            "fetched_at": fetched_at,
            "freshness": "retrieved_at",
            "summary": "",
        }
        _copy_feed_metadata(item, feed_conf, tag, category)
        items.append(item)
        if len(items) >= cap:
            break

    return items


def _copy_feed_metadata(
    item: dict,
    feed_conf: dict,
    tag: str = "",
    category: str = "",
) -> None:
    """Attach feed-level routing and trust metadata to collected items."""
    if tag:
        item["tag"] = tag
    if category:
        item["category"] = category
    for key in ("reliability", "analysis_mode"):
        if feed_conf.get(key):
            item[key] = feed_conf[key]


def _looks_like_article_link(base_netloc: str, href: str, title: str) -> bool:
    if not href or not title:
        return False
    normalized_title = " ".join(title.split())
    if len(normalized_title) < 18 or len(normalized_title) > 180:
        return False
    if len(normalized_title.split()) < 3:
        return False
    title_lower = normalized_title.lower()
    if title_lower in _HTML_INDEX_IGNORE_TITLES:
        return False
    if any(ignored in title_lower for ignored in ("subscribe", "sign in", "log in")):
        return False

    absolute = urljoin(f"https://{base_netloc}", href)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc.endswith(base_netloc):
        return False
    if parsed.path in {"", "/"}:
        return False
    if any(part in parsed.path.lower() for part in _HTML_INDEX_IGNORE_PATH_PARTS):
        return False
    if parsed.path.endswith(".xml"):
        return False
    return True


def _fetch_from_freshrss(rss_config: dict) -> list[dict]:
    """Fetch unread items from FreshRSS Google Reader-compatible API."""
    base = rss_config["freshrss_url"].rstrip("/")
    user = rss_config.get("freshrss_user", "")
    password = rss_config.get("freshrss_password", "")

    try:
        # Authenticate
        auth_resp = requests.post(
            f"{base}/accounts/ClientLogin",
            data={"Email": user, "Passwd": password},
            timeout=10,
        )
        auth_resp.raise_for_status()
        auth_token = None
        for line in auth_resp.text.strip().split("\n"):
            if line.startswith("Auth="):
                auth_token = line[5:]
                break

        if not auth_token:
            log.error("FreshRSS auth failed — no token")
            return []

        headers = {"Authorization": f"GoogleLogin auth={auth_token}"}

        # Fetch unread items
        items_resp = requests.get(
            f"{base}/reader/api/0/stream/contents/reading-list",
            params={"n": 100, "xt": "user/-/state/com.google/read"},
            headers=headers,
            timeout=15,
        )
        items_resp.raise_for_status()
        data = items_resp.json()

        results = []
        for item in data.get("items", []):
            results.append({
                "source": item.get("origin", {}).get("title", "RSS"),
                "title": item.get("title", "").strip(),
                "url": next(
                    (a["href"] for a in item.get("alternate", []) if "href" in a),
                    "",
                ),
                "published": datetime.fromtimestamp(
                    item.get("published", 0), tz=timezone.utc
                ).isoformat(),
                "summary": _clean_summary(
                    item.get("summary", {}).get("content", "")
                ),
            })

        return results

    except Exception as e:
        log.error(f"FreshRSS fetch failed: {e}")
        return _fetch_direct(rss_config)  # fallback to direct


def _parse_feed_date(entry) -> Optional[datetime]:
    """Extract and parse date from a feed entry. Always returns UTC-aware."""
    for field in ("published_parsed", "updated_parsed"):
        val = entry.get(field)
        if val:
            return datetime.fromtimestamp(timegm(val), tz=timezone.utc)

    for field in ("published", "updated"):
        val = entry.get(field)
        if val:
            try:
                dt = dateparser.parse(val)
            except Exception:
                continue
            if dt is None:
                continue
            # dateparser may return a naive datetime for strings without an
            # explicit offset; assume UTC so downstream comparisons don't raise.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt

    return None


def _clean_summary(raw: str) -> str:
    """Strip HTML and truncate summary."""
    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self._parts = []
        def handle_data(self, d):
            self._parts.append(d)
        def get_text(self):
            return " ".join(self._parts)

    stripper = _Stripper()
    stripper.feed(raw)
    text = " ".join(stripper.get_text().split())  # collapse whitespace
    if len(text) > 400:
        text = text[:397] + "..."
    return text
