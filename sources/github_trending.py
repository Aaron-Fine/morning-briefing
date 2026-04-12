"""Fetch trending GitHub repositories.

GitHub has no official trending API, so we scrape the trending page
or use a lightweight proxy. Falls back gracefully.
"""

import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

TRENDING_URL = "https://github.com/trending"


def fetch_github_trending(config: dict) -> list[dict]:
    """Return today's trending GitHub repos.

    Returns list of dicts: {name, url, description, language, stars_today}
    """
    gh_config = config.get("github_trending", {})
    count = gh_config.get("count", 5)
    language = gh_config.get("language", "")  # empty = all languages

    try:
        url = TRENDING_URL
        params = {}
        if language:
            url = f"{TRENDING_URL}/{language}"
        params["since"] = "daily"

        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": "MorningDigest/1.0"},
            timeout=15,
        )
        resp.raise_for_status()

        return _parse_trending_page(resp.text, count)

    except Exception as e:
        log.warning(f"GitHub trending fetch failed: {e}")
        return []


def _parse_trending_page(html: str, count: int) -> list[dict]:
    """Parse the GitHub trending HTML page."""
    soup = BeautifulSoup(html, "lxml")
    repos = []

    for article in soup.select("article.Box-row")[:count]:
        # Repo name (org/repo)
        name_el = article.select_one("h2 a")
        if not name_el:
            continue
        name = name_el.get_text(strip=True).replace("\n", "").replace(" ", "")
        url = f"https://github.com{name_el['href']}"

        # Description
        desc_el = article.select_one("p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        # Language
        lang_el = article.select_one("[itemprop='programmingLanguage']")
        language = lang_el.get_text(strip=True) if lang_el else ""

        # Stars today
        stars_today = ""
        spans = article.select("span.d-inline-block.float-sm-right")
        if spans:
            stars_today = spans[0].get_text(strip=True)

        repos.append({
            "name": name,
            "url": url,
            "description": description[:200],
            "language": language,
            "stars_today": stars_today,
        })

    return repos
