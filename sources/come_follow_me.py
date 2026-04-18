"""Determine the current Come Follow Me lesson and provide a scripture/thought."""

import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)

# 2026 Come Follow Me schedule (Old Testament)
# Each entry: (start_date, end_date, lesson_num, reading, title, key_scripture)
# Based on the 2022 Old Testament cycle which repeats in 2026.
# Verify against churchofjesuschrist.org/study/come-follow-me for any 2026-specific adjustments.
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
    ("2026-03-09", "2026-03-15", 10, "Genesis 37-41", "The Lord Was with Joseph", "Genesis 39:2"),
    ("2026-03-16", "2026-03-22", 11, "Genesis 42-50", "God Meant It unto Good", "Genesis 50:20"),
    ("2026-03-23", "2026-03-29", 12, "Exodus 1-6", "I Have Remembered My Covenant", "Exodus 3:14"),
    ("2026-03-30", "2026-04-05", 13, "Easter / General Conference", "Easter and General Conference", "John 11:25"),
    ("2026-04-06", "2026-04-12", 14, "Exodus 7-13", "I Will Pass over You", "Exodus 12:13"),
    ("2026-04-13", "2026-04-19", 15, "Exodus 14-17", "Stand Still, and See the Salvation of the Lord", "Exodus 14:13"),
    ("2026-04-20", "2026-04-26", 16, "Exodus 18-20", "All That the Lord Hath Spoken We Will Do", "Exodus 19:5-6"),
    ("2026-04-27", "2026-05-03", 17, "Exodus 21-24", "We Will Be Obedient", "Exodus 24:7"),
    ("2026-05-04", "2026-05-10", 18, "Exodus 25-27; 30-31", "Holiness to the Lord", "Exodus 25:8"),
    ("2026-05-11", "2026-05-17", 19, "Exodus 28-29; Leviticus 8", "A Kingdom of Priests", "Exodus 28:3"),
    ("2026-05-18", "2026-05-24", 20, "Exodus 32-34", "My Presence Shall Go with Thee", "Exodus 33:14"),
    ("2026-05-25", "2026-05-31", 21, "Exodus 35-40; Leviticus 1; 16; 19", "Holiness to the Lord", "Leviticus 19:2"),
    ("2026-06-01", "2026-06-07", 22, "Numbers 11-14; 20-24", "Rebel Not Ye against the Lord", "Numbers 14:9"),
    ("2026-06-08", "2026-06-14", 23, "Deuteronomy 6-8; 15; 18; 29-30; 34", "Beware Lest Thou Forget the Lord", "Deuteronomy 6:5"),
    ("2026-06-15", "2026-06-21", 24, "Joshua 1-8; 23-24", "Be Strong and of a Good Courage", "Joshua 1:9"),
    ("2026-06-22", "2026-06-28", 25, "Judges 2-4; 6-8; 13-16", "The Lord Raised Up a Deliverer", "Judges 2:16"),
    ("2026-06-29", "2026-07-05", 26, "Ruth; 1 Samuel 1-3", "The Lord Looketh on the Heart", "Ruth 1:16"),
    ("2026-07-06", "2026-07-12", 27, "1 Samuel 8-10; 13; 15-18", "The Battle Is the Lord's", "1 Samuel 17:47"),
    ("2026-07-13", "2026-07-19", 28, "1 Samuel 23-24; 31; 2 Samuel 5-7; 11-12", "Create in Me a Clean Heart", "Psalm 51:10"),
    ("2026-07-20", "2026-07-26", 29, "1 Kings 1-7", "The Lord Gave Solomon Wisdom", "1 Kings 3:9"),
    ("2026-07-27", "2026-08-02", 30, "1 Kings 8-13", "This Is the House of the Lord", "1 Kings 8:30"),
    ("2026-08-03", "2026-08-09", 31, "1 Kings 17-19", "How Long Halt Ye between Two Opinions?", "1 Kings 18:21"),
    ("2026-08-10", "2026-08-16", 32, "2 Kings 2-7", "There Is a Prophet in Israel", "2 Kings 5:8"),
    ("2026-08-17", "2026-08-23", 33, "2 Kings 17-25", "Turn Again to the Lord", "2 Chronicles 36:15-16"),
    ("2026-08-24", "2026-08-30", 34, "Ezra 1; 3-7; Nehemiah 2; 4-6; 8", "We Will Build unto the Lord", "Ezra 1:3"),
    ("2026-08-31", "2026-09-06", 35, "Esther", "The Lord Preserveth the Faithful", "Esther 4:14"),
    ("2026-09-07", "2026-09-13", 36, "Job 1-3; 12-14; 19; 21-24; 38-40; 42", "The Lord Gave, and the Lord Hath Taken Away", "Job 19:25"),
    ("2026-09-14", "2026-09-20", 37, "Psalms 1-2; 8; 19-33", "The Lord Is My Shepherd", "Psalm 23:1"),
    ("2026-09-21", "2026-09-27", 38, "Psalms 34-41; 46-51; 61-66; 69-72", "Create in Me a Clean Heart", "Psalm 51:10"),
    ("2026-09-28", "2026-10-04", 39, "General Conference", "General Conference", "Psalm 46:10"),
    ("2026-10-05", "2026-10-11", 40, "Psalms 73-77; 84-86; 90-92; 95-100; 102-104; 110; 116-117; 119", "O Give Thanks unto the Lord", "Psalm 100:3"),
    ("2026-10-12", "2026-10-18", 41, "Psalms 120-134; 136-139; 146-150", "Let Every Thing That Hath Breath Praise the Lord", "Psalm 150:6"),
    ("2026-10-19", "2026-10-25", 42, "Proverbs 1-4; 15-16; 22; 31; Ecclesiastes 1-3; 11-12", "Happy Is the Man That Findeth Wisdom", "Proverbs 3:5-6"),
    ("2026-10-26", "2026-11-01", 43, "Isaiah 1-12", "A Great Light", "Isaiah 9:6"),
    ("2026-11-02", "2026-11-08", 44, "Isaiah 13-14; 24-30; 35", "The Lord's Hand Is Stretched Out Still", "Isaiah 25:8"),
    ("2026-11-09", "2026-11-15", 45, "Isaiah 36-41", "Be Not Afraid", "Isaiah 41:10"),
    ("2026-11-16", "2026-11-22", 46, "Isaiah 42-49", "A Light to the Gentiles", "Isaiah 49:16"),
    ("2026-11-23", "2026-11-29", 47, "Isaiah 50-57", "He Was Wounded for Our Transgressions", "Isaiah 53:5"),
    ("2026-11-30", "2026-12-06", 48, "Isaiah 58-66", "Arise, Shine; for Thy Light Is Come", "Isaiah 60:1"),
    ("2026-12-07", "2026-12-13", 49, "Jeremiah 1-3; 7; 16-18; 20", "Before Thou Camest Forth I Sanctified Thee", "Jeremiah 1:5"),
    ("2026-12-14", "2026-12-20", 50, "Jeremiah 30-33; 36; Lamentations 1; 3", "I Will Write It in Their Hearts", "Jeremiah 31:33"),
    ("2026-12-21", "2026-12-27", 51, "Ezekiel 1-3; 33-34; 36-37; 47; Daniel 1-2; 6", "I Will Put My Spirit within You", "Ezekiel 37:27"),
]


# General Conference sessions (Saturday + Sunday, first weekend of April and October)
# Sessions run ~10:00 AM and ~2:00 PM MT each day.
GENERAL_CONFERENCE_DATES = [
    date(2026, 4, 4),   # Spring 2026 — Saturday
    date(2026, 4, 5),   # Spring 2026 — Sunday
    date(2026, 10, 3),  # Fall 2026 — Saturday
    date(2026, 10, 4),  # Fall 2026 — Sunday
    date(2027, 4, 3),   # Spring 2027 — Saturday
    date(2027, 4, 4),   # Spring 2027 — Sunday
    date(2027, 10, 2),  # Fall 2027 — Saturday
    date(2027, 10, 3),  # Fall 2027 — Sunday
]


def get_upcoming_church_events(lookahead_days: int = 10) -> list[dict]:
    """Return General Conference sessions within the lookahead window.

    Returns list of dicts: {date, event, description}
    """
    today = date.today()
    cutoff = today + timedelta(days=lookahead_days)
    events = []
    for d in GENERAL_CONFERENCE_DATES:
        if today <= d <= cutoff:
            label = "Saturday" if d.weekday() == 5 else "Sunday"
            season = "Spring" if d.month == 4 else "Fall"
            events.append({
                "date": d.isoformat(),
                "event": f"LDS General Conference — {season} {d.year} ({label})",
                "description": "Worldwide broadcast of LDS General Conference sessions.",
            })
    return events


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
                "date_range": (
                    f"{start.strftime('%B')} {start.day}–{end.day}"
                    if start.month == end.month
                    else f"{start.strftime('%B')} {start.day}–{end.strftime('%B')} {end.day}"
                ),
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
    known = {
        "Moses 1:39": "For behold, this is my work and my glory—to bring to pass the immortality and eternal life of man.",
        "Moses 2:1": "And it came to pass that the Lord spake unto Moses, saying: Behold, I reveal unto you concerning this heaven, and this earth.",
        "Moses 5:11": "Were it not for our transgression we never should have had seed, and never should have known good and evil, and the joy of our redemption.",
        "Moses 6:57": "Wherefore teach it unto your children, that all men, everywhere, must repent, or they can in nowise inherit the kingdom of God.",
        "Moses 7:18": "And the Lord called his people Zion, because they were of one heart and one mind, and dwelt in righteousness; and there was no poor among them.",
        "Genesis 6:9": "Noah was a just man and perfect in his generations, and Noah walked with God.",
        "Abraham 2:11": "I will bless them that bless thee, and curse them that curse thee; and in thee … shall all the families of the earth be blessed.",
        "Genesis 18:14": "Is any thing too hard for the Lord?",
        "Genesis 32:28": "Thy name shall be called no more Jacob, but Israel: for as a prince hast thou power with God and with men, and hast prevailed.",
        "Genesis 39:2": "And the Lord was with Joseph, and he was a prosperous man.",
        "Genesis 50:20": "But as for you, ye thought evil against me; but God meant it unto good, to bring to pass, as it is this day, to save much people alive.",
        "Exodus 3:14": "And God said unto Moses, I AM THAT I AM.",
        "John 11:25": "I am the resurrection, and the life: he that believeth in me, though he were dead, yet shall he live.",
        "Exodus 12:13": "And the blood shall be to you for a token upon the houses where ye are: and when I see the blood, I will pass over you.",
        "Exodus 14:13": "Fear ye not, stand still, and see the salvation of the Lord.",
        "Exodus 19:5-6": "Now therefore, if ye will obey my voice indeed, and keep my covenant, then ye shall be a peculiar treasure unto me above all people.",
        "Exodus 24:7": "All that the Lord hath said will we do, and be obedient.",
        "Exodus 25:8": "And let them make me a sanctuary; that I may dwell among them.",
        "Exodus 28:3": "And thou shalt speak unto all that are wise hearted, whom I have filled with the spirit of wisdom.",
        "Exodus 33:14": "My presence shall go with thee, and I will give thee rest.",
        "Leviticus 19:2": "Ye shall be holy: for I the Lord your God am holy.",
        "Numbers 14:9": "Only rebel not ye against the Lord, neither fear ye the people of the land; for they are bread for us: their defence is departed from them, and the Lord is with us.",
        "Deuteronomy 6:5": "And thou shalt love the Lord thy God with all thine heart, and with all thy soul, and with all thy might.",
        "Joshua 1:9": "Be strong and of a good courage; be not afraid, neither be thou dismayed: for the Lord thy God is with thee whithersoever thou goest.",
        "Judges 2:16": "Nevertheless the Lord raised up judges, which delivered them out of the hand of those that spoiled them.",
        "Ruth 1:16": "Whither thou goest, I will go; and where thou lodgest, I will lodge: thy people shall be my people, and thy God my God.",
        "1 Samuel 17:47": "The battle is the Lord's, and he will give you into our hands.",
        "Psalm 51:10": "Create in me a clean heart, O God; and renew a right spirit within me.",
        "1 Kings 3:9": "Give therefore thy servant an understanding heart to judge thy people, that I may discern between good and bad.",
        "1 Kings 8:30": "And hearken thou to the supplication of thy servant, and of thy people Israel, when they shall pray toward this place.",
        "1 Kings 18:21": "How long halt ye between two opinions? if the Lord be God, follow him.",
        "2 Kings 5:8": "Let him come now to me, and he shall know that there is a prophet in Israel.",
        "2 Chronicles 36:15-16": "The Lord God of their fathers sent to them by his messengers, rising up betimes, and sending; because he had compassion on his people.",
        "Ezra 1:3": "Who is there among you of all his people? his God be with him, and let him go up.",
        "Esther 4:14": "Who knoweth whether thou art come to the kingdom for such a time as this?",
        "Job 19:25": "For I know that my redeemer liveth, and that he shall stand at the latter day upon the earth.",
        "Psalm 23:1": "The Lord is my shepherd; I shall not want.",
        "Psalm 46:10": "Be still, and know that I am God.",
        "Psalm 100:3": "Know ye that the Lord he is God: it is he that hath made us, and not we ourselves; we are his people, and the sheep of his pasture.",
        "Psalm 150:6": "Let every thing that hath breath praise the Lord.",
        "Proverbs 3:5-6": "Trust in the Lord with all thine heart; and lean not unto thine own understanding. In all thy ways acknowledge him, and he shall direct thy paths.",
        "Isaiah 9:6": "For unto us a child is born, unto us a son is given: and the government shall be upon his shoulder.",
        "Isaiah 25:8": "He will swallow up death in victory; and the Lord God shall wipe away tears from off all faces.",
        "Isaiah 41:10": "Fear thou not; for I am with thee: be not dismayed; for I am thy God.",
        "Isaiah 49:16": "Behold, I have graven thee upon the palms of my hands; thy walls are continually before me.",
        "Isaiah 53:5": "But he was wounded for our transgressions, he was bruised for our iniquities: the chastisement of our peace was upon him; and with his stripes we are healed.",
        "Isaiah 60:1": "Arise, shine; for thy light is come, and the glory of the Lord is risen upon thee.",
        "Jeremiah 1:5": "Before I formed thee in the belly I knew thee; and before thou camest forth out of the womb I sanctified thee.",
        "Jeremiah 31:33": "I will put my law in their inward parts, and write it in their hearts; and will be their God, and they shall be my people.",
        "Ezekiel 37:27": "My tabernacle also shall be with them: yea, I will be their God, and they shall be my people.",
    }
    return known.get(reference, "")
