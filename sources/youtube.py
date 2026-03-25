"""Fetch recent uploads from YouTube channels via public channel RSS feeds.

No API key required — uses YouTube's public Atom feeds parsed with feedparser.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import feedparser
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

log = logging.getLogger(__name__)

YOUTUBE_RSS_BASE = "https://www.youtube.com/feeds/videos.xml?channel_id="


def fetch_recent_videos(config: dict) -> list[dict]:
    """Return recent videos from Always Watch channels.

    Returns list of dicts: {channel, title, video_id, url, published, description}
    Includes transcript field when auto-captions are available.
    """
    yt_config = config.get("youtube", {})
    channels = yt_config.get("always_watch", [])
    lookback = yt_config.get("lookback_hours", 48)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)

    videos = []

    for ch in channels:
        try:
            feed = feedparser.parse(
                YOUTUBE_RSS_BASE + ch["id"],
                request_headers={"User-Agent": "MorningDigest/1.0"},
            )
            for entry in feed.entries:
                published = _parse_entry_date(entry)
                if not published or published < cutoff:
                    continue

                video_id = _extract_video_id(entry)
                if not video_id:
                    continue

                transcript = _get_transcript(video_id)
                video = {
                    "channel": ch["name"],
                    "title": entry.get("title", "").strip(),
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "published": published.isoformat(),
                    "description": _get_description(entry)[:800],
                }
                if transcript:
                    video["transcript"] = transcript
                videos.append(video)

        except Exception as e:
            log.warning(f"Failed to fetch videos for {ch['name']}: {e}")
            continue

    videos.sort(key=lambda v: v["published"], reverse=True)
    return videos


def _extract_video_id(entry) -> Optional[str]:
    """Extract video ID from entry — prefer yt:videoId tag, fall back to link URL."""
    # feedparser exposes yt:videoId as entry.yt_videoid
    video_id = entry.get("yt_videoid", "")
    if video_id:
        return video_id
    # Fall back: parse from watch URL
    link = entry.get("link", "")
    if "v=" in link:
        return link.split("v=")[-1].split("&")[0]
    return None


def _parse_entry_date(entry) -> Optional[datetime]:
    """Parse published date from feed entry."""
    from time import mktime
    for field in ("published_parsed", "updated_parsed"):
        val = entry.get(field)
        if val:
            return datetime.fromtimestamp(mktime(val), tz=timezone.utc)
    return None


def _get_description(entry) -> str:
    """Extract video description from feed entry."""
    # feedparser maps media:description into summary for YouTube feeds
    return entry.get("summary", "")


def _get_transcript(video_id: str, max_chars: int = 2000) -> Optional[str]:
    """Fetch auto-generated or manual transcript, truncated to max_chars.

    Returns None if no transcript is available.
    """
    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join(s["text"] for s in segments)
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "…"
        return text
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except Exception as e:
        log.debug(f"Transcript unavailable for {video_id}: {e}")
        return None
