"""Fetch recent uploads from YouTube channels via the Data API v3."""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import requests

log = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def _get_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key:
        raise ValueError("YOUTUBE_API_KEY environment variable not set")
    return key


def _get_uploads_playlist_id(channel_id: str) -> str:
    """Convert channel ID to uploads playlist ID (UC... -> UU...)."""
    return "UU" + channel_id[2:]


def fetch_recent_videos(config: dict) -> list[dict]:
    """Return recent videos from Always Watch channels.
    
    Returns list of dicts: {channel, title, video_id, url, published, duration_label}
    """
    api_key = _get_api_key()
    yt_config = config.get("youtube", {})
    channels = yt_config.get("always_watch", [])
    lookback = yt_config.get("lookback_hours", 48)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)

    videos = []

    for ch in channels:
        try:
            playlist_id = _get_uploads_playlist_id(ch["id"])
            resp = requests.get(
                f"{YOUTUBE_API_BASE}/playlistItems",
                params={
                    "part": "snippet",
                    "playlistId": playlist_id,
                    "maxResults": 5,
                    "key": api_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])

            recent_items = []
            for item in items:
                snippet = item["snippet"]
                published = datetime.fromisoformat(
                    snippet["publishedAt"].replace("Z", "+00:00")
                )
                if published < cutoff:
                    continue
                recent_items.append((snippet, published))

            # Batch fetch durations for all recent videos from this channel
            video_ids = [s["resourceId"]["videoId"] for s, _ in recent_items]
            durations = _get_video_durations(video_ids, api_key) if video_ids else {}

            for snippet, published in recent_items:
                video_id = snippet["resourceId"]["videoId"]
                videos.append({
                    "channel": ch["name"],
                    "title": snippet["title"],
                    "video_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "published": published.isoformat(),
                    "duration_label": durations.get(video_id, ""),
                    "description": snippet.get("description", "")[:300],
                })

        except Exception as e:
            log.warning(f"Failed to fetch videos for {ch['name']}: {e}")
            continue

    # Sort by publish time, newest first
    videos.sort(key=lambda v: v["published"], reverse=True)
    return videos


def _get_video_durations(video_ids: list[str], api_key: str) -> dict[str, str]:
    """Batch-fetch human-readable durations for multiple videos (max 50 per call)."""
    if not video_ids:
        return {}
    durations = {}
    # YouTube API accepts up to 50 IDs per request
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        try:
            resp = requests.get(
                f"{YOUTUBE_API_BASE}/videos",
                params={
                    "part": "contentDetails",
                    "id": ",".join(batch),
                    "key": api_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                vid = item["id"]
                dur = item.get("contentDetails", {}).get("duration", "")
                durations[vid] = _parse_iso_duration(dur)
        except Exception as e:
            log.warning(f"Batch duration fetch failed: {e}")
    return durations


def _parse_iso_duration(iso: str) -> str:
    """Convert ISO 8601 duration (PT1H23M45S) to human-readable."""
    import re
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not match:
        return ""
    hours, minutes, seconds = match.groups()
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    elif hours:
        parts.append("0m")
    if not parts and seconds:
        parts.append(f"{seconds}s")
    return " ".join(parts)
