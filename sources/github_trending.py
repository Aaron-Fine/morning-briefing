"""Fetch trending GitHub repositories.

GitHub has no official trending API, so we scrape the trending page.
Falls back gracefully.
"""

import logging
from html.parser import HTMLParser

from sources._http import http_get_text

log = logging.getLogger(__name__)

TRENDING_URL = "https://github.com/trending"


def fetch_github_trending(config: dict) -> list[dict]:
    """Return today's trending GitHub repos.

    Returns list of dicts: {name, url, description, language, stars_today}
    """
    gh_config = config.get("github_trending", {})
    count = gh_config.get("count", 5)
    language = gh_config.get("language", "")  # empty = all languages

    url = f"{TRENDING_URL}/{language}" if language else TRENDING_URL
    html = http_get_text(
        url, params={"since": "daily"}, label="GitHub trending"
    )
    if html is None:
        return []
    return _parse_trending_page(html, count)


def _parse_trending_page(html: str, count: int) -> list[dict]:
    """Parse the GitHub trending HTML page."""
    parser = _TrendingParser(count)
    parser.feed(html)
    return parser.repos


class _TrendingParser(HTMLParser):
    """Minimal parser for GitHub Trending article cards."""

    def __init__(self, count: int):
        super().__init__()
        self.count = count
        self.repos: list[dict] = []
        self._article_depth = 0
        self._current: dict | None = None
        self._capture: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        classes = attrs_map.get("class", "").split()

        if tag == "article" and "Box-row" in classes and len(self.repos) < self.count:
            self._article_depth = 1
            self._current = {
                "name": "",
                "url": "",
                "description": "",
                "language": "",
                "stars_today": "",
            }
            return

        if self._article_depth <= 0 or self._current is None:
            return

        if tag == "article":
            self._article_depth += 1
            return

        if tag == "a" and self._current["url"] == "" and attrs_map.get("href", "").startswith("/"):
            self._current["url"] = f"https://github.com{attrs_map['href']}"
            self._capture = "name"
            self._parts = []
            return

        if tag == "p" and self._current["description"] == "":
            self._capture = "description"
            self._parts = []
            return

        if attrs_map.get("itemprop") == "programmingLanguage":
            self._capture = "language"
            self._parts = []
            return

        if tag == "span" and "float-sm-right" in classes:
            self._capture = "stars_today"
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._article_depth <= 0 or self._current is None:
            return

        if self._capture and tag in {"a", "p", "span"}:
            value = " ".join("".join(self._parts).split())
            if self._capture == "name":
                value = value.replace(" / ", "/").replace(" ", "")
            if self._capture == "description":
                value = value[:200]
            self._current[self._capture] = value
            self._capture = None
            self._parts = []
            return

        if tag == "article":
            self._article_depth -= 1
            if self._article_depth == 0 and self._current:
                if self._current["name"] and self._current["url"]:
                    self.repos.append(self._current)
                self._current = None
