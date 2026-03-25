"""Determine the current Come Follow Me lesson and provide a scripture/thought."""

import logging
from datetime import datetime, date
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# 2026 Come Follow Me schedule (Old Testament)
# Each entry: (start_date, end_date, lesson_num, reading, title, key_scripture)
SCHEDULE_2026 = [
    ("2026-01-05", "2026-01-11", 1, "Moses 1; Abraham 3", "This Is My Work and My Glory", "Moses 1:39"),
    ("2026-01-12", "2026-01-18", 2, "Genesis 1-2; Moses 2-3; Abraham 4-5", "In the Beginning", "Moses 2:1"),
    ("2026-01-19", "2026-01-25", 3, "Genesis 3-4; Moses 4-5", "The Fall", "Moses 5:11"),
    ("2026-01-26", "2026-02-01", 4, "Genesis 5; Moses 6", "Walk with God", "Moses 6:57"),
    ("2026-02-02", "2026-02-08", 5, "Moses 7", "Zion", "Moses 7:18"),
    ("2026-02-09", "2026-02-15", 6, "Genesis 6-11; Moses 8", "The True Ark", "Genesis 6:9"),
    ("2026-02-16", "2026-02-22", 7, "Genesis 12-17; Abraham 1-2", "The Great Promise", "Abraham 2:11"),
    ("2026-02-23", "2026-03-01", 8, "Genesis 18-23", "Is Any Thing Too Hard for the Lord?", "Genesis 18:14"),
    ("2026-03-02", "2026-03-08", 9, "Genesis 24-33", "Let God Prevail", "Genesis 32:28"),
    ("2026-03-09", "2026-03-15", 10, "Genesis 37-41", "The Lord Was with Joseph", "Genesis 39:2"),  # note: 34-36 included in study
    ("2026-03-16", "2026-03-22", 11, "Genesis 42-50", "God Meant It unto Good", "Genesis 50:20"),
    ("2026-03-23", "2026-03-29", 12, "Exodus 1-6", "I Have Remembered My Covenant", "Exodus 3:14"),
    ("2026-03-30", "2026-04-05", 13, "Easter / General Conference", "Easter and General Conference", "John 11:25"),
    # ... extend as needed through December
]


def get_current_lesson(config: dict) -> dict:
    """Return this week's Come Follow Me lesson info.
    
    Returns dict: {reading, title, key_scripture, scripture_text, reflection, 
                   lesson_url, date_range}
    """
    today = date.today()

    for start_str, end_str, num, reading, title, key_ref in SCHEDULE_2026:
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
        if start <= today <= end:
            lesson_url = (
                f"{config.get('come_follow_me', {}).get('base_url', '')}/{num + 1}"
            )
            return {
                "reading": reading,
                "title": title,
                "key_scripture": key_ref,
                "scripture_text": _get_scripture_text(key_ref),
                "date_range": f"{start.strftime('%B %-d')}–{end.strftime('%-d')}",
                "lesson_url": lesson_url,
                "lesson_num": num,
            }

    # Fallback if no match
    return {
        "reading": "",
        "title": "Come, Follow Me",
        "key_scripture": "",
        "scripture_text": "",
        "date_range": "",
        "lesson_url": "",
        "lesson_num": 0,
    }


def _get_scripture_text(reference: str) -> str:
    """Return the text of a known key scripture.
    
    For a production version, this could scrape churchofjesuschrist.org/scriptures
    or use a local scripture database. For now, we include the key verses from
    the 2026 schedule and let Claude fill in context.
    """
    # Key verses for the schedule — extend as lessons progress
    known = {
        "Moses 1:39": "For behold, this is my work and my glory—to bring to pass the immortality and eternal life of man.",
        "Genesis 18:14": "Is any thing too hard for the Lord?",
        "Genesis 32:28": "Thy name shall be called no more Jacob, but Israel: for as a prince hast thou power with God and with men, and hast prevailed.",
        "Genesis 39:2": "And the Lord was with Joseph, and he was a prosperous man.",
        "Genesis 50:20": "But as for you, ye thought evil against me; but God meant it unto good, to bring to pass, as it is this day, to save much people alive.",
        "Exodus 3:14": "And God said unto Moses, I AM THAT I AM.",
        "John 11:25": "I am the resurrection, and the life: he that believeth in me, though he were dead, yet shall he live.",
    }
    return known.get(reference, "")
