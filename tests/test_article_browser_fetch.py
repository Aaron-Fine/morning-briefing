"""Tests for browser-backed article fetch helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.article_browser_fetch import (
    _clean_markdown,
    _cookies_to_browser_format,
    _coerce_markdown,
)
from sources.article_fetch import load_cookies_file


def test_cookies_to_browser_format_converts_netscape_cookie(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tTRUE\t9999999999\tsession\tabc\n",
        encoding="utf-8",
    )
    jar = load_cookies_file(str(path))
    cookies = _cookies_to_browser_format(jar)
    assert cookies == [
        {
            "name": "session",
            "value": "abc",
            "domain": ".example.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
            "expires": 9999999999,
        }
    ]


def test_clean_markdown_compacts_lines():
    assert _clean_markdown("  A   line  \n\n B\tline ") == "A line\nB line"


def test_coerce_markdown_handles_generation_result_shape():
    class Markdown:
        raw_markdown = "Raw text"

    assert _coerce_markdown(Markdown()) == "Raw text"
