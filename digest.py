#!/usr/bin/env python3
"""Morning Digest — main orchestrator.

Collects data from all configured sources, sends it to Claude for synthesis
and editorial judgment, renders the HTML email, and sends it.
"""

import os
import sys
import json
import logging
from datetime import datetime, date
from pathlib import Path

import yaml
import anthropic

from sources.youtube import fetch_recent_videos
from sources.weather import fetch_weather
from sources.markets import fetch_markets
from sources.rss_feeds import fetch_rss
from sources.come_follow_me import get_current_lesson
from templates.email_template import render_email
from sender import send_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("digest")

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def collect_sources(config: dict) -> dict:
    """Gather raw data from all sources."""
    log.info("Collecting from sources...")
    
    data = {}

    # Weather
    log.info("  → Weather")
    data["weather"] = fetch_weather(config)

    # Markets
    if config.get("digest", {}).get("markets", {}).get("enabled", True):
        log.info("  → Markets")
        data["markets"] = fetch_markets(config)

    # Come Follow Me
    if config.get("digest", {}).get("spiritual", {}).get("enabled", True):
        log.info("  → Come Follow Me")
        data["come_follow_me"] = get_current_lesson(config)

    # YouTube
    log.info("  → YouTube")
    try:
        data["youtube"] = fetch_recent_videos(config)
    except Exception as e:
        log.warning(f"  YouTube failed: {e}")
        data["youtube"] = []

    # RSS feeds
    log.info("  → RSS feeds")
    data["rss"] = fetch_rss(config)

    # Market count
    data["source_counts"] = {
        "youtube_videos": len(data.get("youtube", [])),
        "rss_items": len(data.get("rss", [])),
        "youtube_channels": len(config.get("youtube", {}).get("always_watch", [])),
    }

    log.info(
        f"  Collected: {data['source_counts']['rss_items']} RSS items, "
        f"{data['source_counts']['youtube_videos']} YouTube videos"
    )
    return data


def build_claude_prompt(source_data: dict, config: dict) -> str:
    """Build the system + user prompt for Claude to synthesize the digest."""
    
    today = datetime.now()
    is_friday = today.weekday() == 4
    day_name = today.strftime("%A")
    date_display = today.strftime("%A, %B %-d, %Y")

    cfm = source_data.get("come_follow_me", {})
    weather = source_data.get("weather", {})
    markets = source_data.get("markets", [])
    youtube = source_data.get("youtube", [])
    rss = source_data.get("rss", [])

    system_prompt = f"""You are the editor of Aaron's Morning Digest, a daily email briefing. 
Your voice is that of an informed colleague — direct, analytical, occasionally wry. Never newscaster. 
Never blog-post. Think Philip DeFranco's story selection instincts crossed with Belle of the Ranch's 
"medium dive" depth on carefully selected topics.

Today is {date_display}. Aaron lives in Providence, Utah (Cache Valley).

OUTPUT FORMAT: You must respond with a single valid JSON object (no markdown fencing, no preamble).
The JSON must match this exact structure:

{{
  "at_a_glance": [
    {{
      "tag": "war|ai|domestic|defense|local",
      "tag_label": "War|AI|US|Defense|Local",
      "headline": "short headline",
      "context": "1-3 sentences of context",
      "links": [{{"url": "...", "label": "Source: title"}}]
    }}
  ],
  "deep_dives": [
    {{
      "headline": "...",
      "body": "<p>paragraph 1</p><p>paragraph 2</p>...",
      "why_it_matters": "1-2 sentences connecting to Aaron's interests",
      "further_reading": [{{"url": "...", "title": "...", "source": "outlet name"}}]
    }}
  ],
  "youtube_summaries": [
    {{
      "video_id": "...",
      "summary": "2-3 sentence summary of why this is worth watching",
      "link": [{{"url": "...", "label": "Source: title"}}]
    }}
  ],
  "local_items": ["<strong>Bold headline</strong> — context sentence."],
  "week_ahead": [{{"date": "Mon", "event": "description"}}],
  "spiritual_reflection": "2-3 sentences connecting this week's scripture study lesson to today's world. Thoughtful, not preachy.",
  "atlantic_note": "<p>Brief note on current Atlantic content worth reading.</p>",
  {'"weekend_reads": [' if is_friday else ''}
  {'{{"url": "...", "title": "...", "source": "...", "read_time": "~N min", "description": "1 sentence pitch"}}' if is_friday else ''}
  {'],' if is_friday else ''}
}}

RULES:
- At a Glance: {config['digest']['at_a_glance']['normal_items']} items on a normal day, up to {config['digest']['at_a_glance']['max_items']} on busy days, minimum {config['digest']['at_a_glance']['min_items']}
- Deep Dives: exactly {config['digest']['deep_dives']['count']}, with Further Reading links (1-2 per dive)
- Skip celebrity gossip and internet drama unless linked to a topic discussed elsewhere
- Primary topics: {', '.join(config['topics']['primary'])}
- Secondary topics: {', '.join(config['topics']['secondary'])}
- Tertiary topics: {', '.join(config['topics']['tertiary'])}
- Professional context: DoD / Dept of War, missile warning/defense, UARC/FFRDC, space technology
- For YouTube, write a 2-3 sentence summary for each video explaining why it's worth watching
- Local items: Cache Valley focus, max {config['digest']['local']['max_items']} items
- Week ahead: {config['digest']['week_ahead']['count']} upcoming events worth knowing about
- Deep dive body uses <p> tags for paragraphs
- All URLs in output must come from the source data below — never fabricate URLs
- It is better to leave out a section than to make up data for a section
{"- Include weekend_reads: 3 long-form pieces worth setting aside time for this weekend" if is_friday else "- This is not Friday, so omit weekend_reads from the JSON"}
"""

    user_content = f"""Here is today's source data. Synthesize this into the digest.

=== COME FOLLOW ME (this week) ===
Reading: {cfm.get('reading', 'N/A')}
Title: "{cfm.get('title', 'N/A')}"
Key Scripture: {cfm.get('key_scripture', 'N/A')}
Text: "{cfm.get('scripture_text', '')}"
Date Range: {cfm.get('date_range', '')}

=== WEATHER ===
{json.dumps(weather, indent=2)}

=== MARKETS ===
{json.dumps(markets, indent=2)}

=== YOUTUBE (new uploads from Always Watch channels) ===
{json.dumps(youtube, indent=2) if youtube else "No new uploads in the past 48 hours."}

=== RSS / NEWS ({len(rss)} items) ===
{json.dumps(rss[:60], indent=2)}

Remember: output ONLY valid JSON, no markdown fencing, no commentary outside the JSON.
"""

    return system_prompt, user_content


def call_claude(system_prompt: str, user_content: str, config: dict) -> dict:
    """Send prompt to Claude and parse the JSON response."""
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

    model = config.get("claude", {}).get("model", "claude-sonnet-4-20250514")
    max_tokens = config.get("claude", {}).get("max_tokens", 8000)

    log.info(f"Calling Claude ({model})...")

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fencing if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]  # remove first line
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse Claude response as JSON: {e}")
        log.error(f"Raw response (first 500 chars): {raw[:500]}")
        raise


def assemble_template_data(
    claude_output: dict, source_data: dict, config: dict
) -> dict:
    """Merge Claude's editorial output with raw source data for template rendering."""
    today = datetime.now()
    
    weather = source_data.get("weather", {})
    markets = source_data.get("markets", [])
    cfm = source_data.get("come_follow_me", {})
    youtube_raw = source_data.get("youtube", [])

    # Merge YouTube summaries from Claude with raw video data
    yt_summaries = {
        s["video_id"]: s["summary"]
        for s in claude_output.get("youtube_summaries", [])
    }
    youtube_videos = []
    for v in youtube_raw:
        v["summary"] = yt_summaries.get(v["video_id"], "")
        youtube_videos.append(v)

    # Count channels with no uploads
    all_channels = config.get("youtube", {}).get("always_watch", [])
    channels_with_uploads = {v["channel"] for v in youtube_videos}
    quiet_count = len(all_channels) - len(channels_with_uploads)
    youtube_quiet_note = ""
    if quiet_count > 0:
        youtube_quiet_note = (
            f"No new uploads from the other {quiet_count} "
            f"Always Watch channels in the past 48 hours."
        )

    # Spiritual thought
    spiritual = None
    if cfm.get("scripture_text"):
        spiritual = {
            **cfm,
            "reflection": claude_output.get("spiritual_reflection", ""),
        }

    return {
        "date_display": today.strftime("%A, %B %-d, %Y"),
        "generated_at": today.strftime("%-I:%M %p %Z"),
        "spiritual": spiritual,
        "weather": weather,
        "markets": markets,
        "at_a_glance": claude_output.get("at_a_glance", []),
        "youtube_videos": youtube_videos,
        "youtube_quiet_note": youtube_quiet_note,
        "youtube_channel_count": len(all_channels),
        "local_items": claude_output.get("local_items", []),
        "week_ahead": claude_output.get("week_ahead", []),
        "atlantic_note": claude_output.get("atlantic_note", ""),
        "weekend_reads": claude_output.get("weekend_reads", []),
        "deep_dives": claude_output.get("deep_dives", []),
    }


def run():
    """Main entry point."""
    log.info("=== Morning Digest starting ===")

    config = load_config()

    # 1. Collect raw data from all sources
    source_data = collect_sources(config)

    # 2. Build prompt and call Claude
    system_prompt, user_content = build_claude_prompt(source_data, config)
    claude_output = call_claude(system_prompt, user_content, config)

    # 3. Assemble template data
    template_data = assemble_template_data(claude_output, source_data, config)

    # 4. Render HTML
    html = render_email(template_data)

    # 5. Send email
    success = send_digest(html, config)

    if success:
        log.info("=== Digest sent successfully ===")
    else:
        log.error("=== Digest send FAILED ===")
        # Optionally write to file as fallback
        fallback = Path(__file__).parent / "last_digest.html"
        fallback.write_text(html)
        log.info(f"Saved fallback to {fallback}")
        sys.exit(1)


if __name__ == "__main__":
    run()
