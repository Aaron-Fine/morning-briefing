"""Fetch recent uploads from YouTube channels via yt-dlp.

No API key required. yt-dlp handles YouTube's anti-scraping transparently.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

log = logging.getLogger(__name__)

class _SilentLogger:
    """Redirect yt-dlp output to Python logging."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): log.debug(f"yt-dlp: {msg}")
    def error(self, msg): log.debug(f"yt-dlp: {msg}")


# Suppress yt-dlp's own output; skip_download + playlistend keeps it fast
YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "playlistend": 5,      # only fetch the 5 most recent uploads per channel
    "ignoreerrors": True,
    "logger": _SilentLogger(),
}


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
        handle = ch.get("handle", "")
        if not handle:
            log.warning(f"No handle for channel {ch.get('name')} — skipping")
            continue

        url = f"https://www.youtube.com/@{handle}/videos"
        try:
            with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
                info = ydl.extract_info(url, download=False)

            entries = info.get("entries") or []
            for entry in entries:
                if not entry:  # None = members-only or unavailable video
                    continue
                published = _parse_date(entry.get("upload_date"))
                if not published or published < cutoff:
                    continue

                video_id = entry.get("id", "")
                transcript = _get_transcript(video_id) if video_id else None

                video = {
                    "channel": ch["name"],
                    "title": entry.get("title", "").strip(),
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "published": published.isoformat(),
                    "description": (entry.get("description") or "")[:800],
                }
                if transcript:
                    video["transcript"] = transcript
                videos.append(video)

        except Exception as e:
            log.warning(f"yt-dlp failed for {ch['name']} (@{handle}): {e}")

        time.sleep(0.5)

    videos.sort(key=lambda v: v["published"], reverse=True)
    return videos


def _parse_date(upload_date: Optional[str]) -> Optional[datetime]:
    """Parse yt-dlp's YYYYMMDD upload_date string to an aware datetime."""
    if not upload_date or len(upload_date) != 8:
        return None
    try:
        return datetime(
            int(upload_date[:4]),
            int(upload_date[4:6]),
            int(upload_date[6:8]),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _get_transcript(video_id: str, max_chars: int = 2000) -> Optional[str]:
    """Fetch auto-generated or manual transcript, truncated to max_chars."""
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
