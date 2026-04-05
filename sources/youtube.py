"""Fetch transcripts from YouTube analysis channels via yt-dlp.

No API key required. yt-dlp handles YouTube's anti-scraping transparently.
Transcripts are fetched in full for pre-compression before synthesis.
"""

import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Optional


class _ChannelTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _ChannelTimeout("yt-dlp channel fetch timed out")

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

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
    "socket_timeout": 30,  # 30s per-request timeout — prevents indefinite hangs
}


def fetch_analysis_transcripts(config: dict) -> list[dict]:
    """Return recent videos with full transcripts from analysis channels.

    These channels are treated as news/analysis sources — their transcripts
    are pre-compressed and fed into the main synthesis pipeline.

    Returns list of dicts: {channel, title, video_id, url, published, transcript}
    Videos without available transcripts are silently skipped.
    """
    yt_config = config.get("youtube", {})
    channels = yt_config.get("analysis_channels", [])
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
            # Per-channel hard timeout (90s) — yt-dlp can hang indefinitely
            # when YouTube is rate-limiting. signal.alarm only works on Linux/macOS.
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(90)
            try:
                with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
                    info = ydl.extract_info(url, download=False)
            finally:
                signal.alarm(0)  # cancel alarm

            entries = info.get("entries") or []
            for entry in entries:
                if not entry:  # None = members-only or unavailable video
                    continue
                published = _parse_date(entry.get("upload_date"))
                if not published or published < cutoff:
                    continue

                video_id = entry.get("id", "")
                if not video_id:
                    continue

                transcript = _get_transcript(video_id)
                if not transcript:
                    log.info(f"  No transcript for {ch['name']}: {entry.get('title', '?')} — skipping")
                    continue

                videos.append({
                    "channel": ch["name"],
                    "title": entry.get("title", "").strip(),
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "published": published.isoformat(),
                    "transcript": transcript,
                })

        except _ChannelTimeout:
            log.warning(f"yt-dlp timed out for {ch['name']} (@{handle}) — skipping")
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


def _get_transcript(video_id: str, timeout_secs: int = 30) -> Optional[str]:
    """Fetch full auto-generated or manual transcript.

    Uses SIGALRM to enforce a per-transcript timeout since the
    YouTubeTranscriptApi has no built-in timeout parameter.
    """
    def _transcript_timeout_handler(signum, frame):
        raise _ChannelTimeout(f"Transcript fetch timed out for {video_id}")

    try:
        prev_handler = signal.signal(signal.SIGALRM, _transcript_timeout_handler)
        signal.alarm(timeout_secs)
        try:
            api = YouTubeTranscriptApi()
            transcript = api.fetch(video_id)
            return " ".join(snippet.text for snippet in transcript.snippets)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, prev_handler)
    except _ChannelTimeout:
        log.warning(f"Transcript fetch timed out for {video_id} (>{timeout_secs}s)")
        return None
    except Exception as e:
        log.debug(f"Transcript unavailable for {video_id}: {e}")
        return None
