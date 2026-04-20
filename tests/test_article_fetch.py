"""Tests for article fetch helpers."""

import os
import sys
from http.cookiejar import MozillaCookieJar
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.article_fetch import fetch_article_html, load_cookies_file


def test_load_cookies_file_reads_netscape_file(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t9999999999\tsession\tabc\n",
        encoding="utf-8",
    )
    jar = load_cookies_file(str(path))
    assert jar is not None
    assert len(list(jar)) == 1


def test_load_cookies_file_returns_none_for_missing_file(tmp_path):
    assert load_cookies_file(str(tmp_path / "missing.txt")) is None


def test_fetch_article_html_returns_ok_response():
    response = MagicMock(status_code=200, text="<html>ok</html>")
    with patch("sources.article_fetch._session_get", return_value=response):
        result = fetch_article_html("https://example.com")
    assert result.status == "ok"
    assert result.http_status == 200
    assert result.html == "<html>ok</html>"


def test_fetch_article_html_returns_http_error_for_non_2xx():
    response = MagicMock(status_code=403, text="Forbidden")
    with patch("sources.article_fetch._session_get", return_value=response):
        result = fetch_article_html("https://example.com")
    assert result.status == "http_error"
    assert result.http_status == 403
    assert result.html == ""


def test_fetch_article_html_passes_cookies_and_user_agent():
    response = MagicMock(status_code=200, text="ok")
    jar = MozillaCookieJar()
    with patch("sources.article_fetch._session_get", return_value=response) as mock_get:
        fetch_article_html("https://example.com", cookies=jar, user_agent="X/1")
    _, kwargs = mock_get.call_args
    assert kwargs["cookies"] is jar
    assert kwargs["headers"]["User-Agent"] == "X/1"


def test_fetch_article_html_catches_exception():
    with patch("sources.article_fetch._session_get", side_effect=RuntimeError("boom")):
        result = fetch_article_html("https://example.com")
    assert result.status == "http_error"
    assert result.http_status is None
    assert "boom" in result.error
