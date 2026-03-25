#!/usr/bin/env python3
"""Morning Digest — main orchestrator.

Collects data from all configured sources, sends it to Claude for synthesis
and editorial judgment, renders the HTML email, and sends it.
"""

import json
import logging
import sys
import time
from datetime import datetime, date
from pathlib import Path

import anthropic
import yaml

from sources.youtube import fetch_recent_videos
from sources.weather import fetch_weather
from sources.markets import fetch_markets
from sources.economic_calendar import fetch_economic_calendar
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

    # Economic calendar
    log.info("  → Economic calendar")
    data["economic_calendar"] = fetch_economic_calendar(config)

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

    # Local news (separate from main RSS so Claude can distinguish them)
    local_sources = config.get("local_news", {}).get("sources", [])
    if local_sources:
        log.info("  → Local news")
        local_rss_config = {"feeds": local_sources, "provider": "direct"}
        data["local_news"] = fetch_rss(local_rss_config)
    else:
        data["local_news"] = []

    # Source counts
    data["source_counts"] = {
        "youtube_videos": len(data.get("youtube", [])),
        "rss_items": len(data.get("rss", [])),
        "local_news_items": len(data.get("local_news", [])),
        "youtube_channels": len(config.get("youtube", {}).get("always_watch", [])),
    }

    log.info(
        f"  Collected: {data['source_counts']['rss_items']} RSS items, "
        f"{data['source_counts']['local_news_items']} local news items, "
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
    economic_calendar = source_data.get("economic_calendar", [])
    youtube = source_data.get("youtube", [])
    rss = source_data.get("rss", [])

    weekend_reads_schema = ""
    if is_friday:
        weekend_reads_schema = """  "weekend_reads": [
    {{"url": "...", "title": "...", "source": "...", "read_time": "~N min", "description": "1 sentence pitch"}}
  ],"""

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
      "tag": "war|ai|domestic|defense|space|tech|local|science",
      "tag_label": "War|AI|US|Defense|Space|Tech|Local|Science",
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
{weekend_reads_schema}
}}

RULES:
- At a Glance: {config['digest']['at_a_glance']['normal_items']} items on a normal day, up to {config['digest']['at_a_glance']['max_items']} on busy days, minimum {config['digest']['at_a_glance']['min_items']}
- Deep Dives: exactly {config['digest']['deep_dives']['count']}, with Further Reading links (1-2 per dive)
- Skip celebrity gossip and internet drama unless linked to a topic discussed elsewhere
- Tags: war (conflicts/geopolitics), ai (AI/LLMs/agentic), domestic (US politics/policy), defense (DoD/missile/military), space (launches/satellites/exploration), tech (self-hosting/EVs/consumer tech/open source), local (Cache Valley/Utah), science (research/applied science)
- Primary topics: {', '.join(config['topics']['primary'])}
- Secondary topics: {', '.join(config['topics']['secondary'])}
- Tertiary topics: {', '.join(config['topics']['tertiary'])}
- Professional context: DoD / Dept of War, missile warning/defense, UARC/FFRDC, space technology.
  Defense and space stories with substantive new developments (new contracts, test results,
  policy shifts, budget moves, launches) are strong deep dive candidates. Do not manufacture importance —
  a slow news day in these areas is fine to reflect honestly.
- For YouTube, write a 2-3 sentence summary for each video explaining what it covers and why it's worth watching. Videos include a "transcript" field with the opening portion of the auto-generated transcript when available — use it for accurate content summaries. Fall back to the description field if no transcript is present.
- Local items: Cache Valley focus, max {config['digest']['local']['max_items']} items. Use the LOCAL NEWS section as your source for these — do not fabricate local stories. Omit the section entirely if no qualifying events are found.
- Week ahead: up to {config['digest']['week_ahead']['count']} upcoming events. Draw primarily from the ECONOMIC CALENDAR section (Fed decisions, CPI, jobs reports). Supplement with events explicitly dated in news articles. Do not infer or invent events. Omit the section entirely if nothing qualifies.
- Deep dive body uses <p> tags for paragraphs
- All URLs in output must come from the source data below — never fabricate URLs
- It is better to leave out a section entirely than to make up data for it. If a section has no relevant source data, omit it or return an empty array.
- SOURCE HANDLING — items with "tag": "compress" in the source data are AI-generated
  newsletters wrapped in heavy editorial padding. Extract ONLY concrete facts, product
  names, data points, and named examples. Strip all framing, rhetorical questions, and
  hype. A long compress-tagged piece yields at most 2-3 bullet-worthy facts, or
  supporting context for a Deep Dive sourced primarily from harder journalism. Never
  let its prose style leak into the digest voice.
{"- Include weekend_reads: 3 long-form pieces worth setting aside time for this weekend. URLs must come from source data." if is_friday else "- This is not Friday, so omit weekend_reads from the JSON."}
"""

    local_news = source_data.get("local_news", [])
    rss_display = rss[:80]
    rss_truncated = len(rss) - len(rss_display)

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

=== ECONOMIC CALENDAR (next 7 days, US high/medium-impact events) ===
{json.dumps(economic_calendar, indent=2) if economic_calendar else "No upcoming events found."}

=== YOUTUBE (new uploads from Always Watch channels) ===
{json.dumps(youtube, indent=2) if youtube else "No new uploads in the past 48 hours."}

=== RSS / NEWS ({len(rss)} items{f', showing first 80 — {rss_truncated} older items omitted' if rss_truncated > 0 else ''}) ===
{json.dumps(rss_display, indent=2)}

=== LOCAL NEWS ({len(local_news)} items) ===
{json.dumps(local_news, indent=2) if local_news else "No local news items available."}

Remember: output ONLY valid JSON, no markdown fencing, no commentary outside the JSON.
"""

    return system_prompt, user_content


def call_claude(system_prompt: str, user_content: str, config: dict, max_retries: int = 2) -> dict:
    """Send prompt to Claude and parse the JSON response.

    Retries on transient errors (overloaded, network issues) with exponential backoff.
    """
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

    model = config.get("claude", {}).get("model", "claude-opus-4-20250514")
    max_tokens = config.get("claude", {}).get("max_tokens", 8000)

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait = 2 ** attempt * 5  # 10s, 20s
                log.info(f"Retrying in {wait}s (attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait)

            log.info(f"Calling Claude ({model})...")
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            break
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            last_error = e
            log.warning(f"Claude API error: {e}")
            if attempt == max_retries:
                raise
            # Only retry on overloaded (529) or server errors (5xx) or connection issues
            if isinstance(e, anthropic.APIStatusError) and e.status_code < 500:
                raise
            continue

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

    # Build dynamic source list for footer
    rss_names = [f["name"] for f in config.get("rss", {}).get("feeds", [])]
    local_names = [s["name"] for s in config.get("local_news", {}).get("sources", [])]
    all_source_names = rss_names + local_names
    rss_source_names = ", ".join(all_source_names) if all_source_names else "RSS feeds"

    return {
        "date_display": today.strftime("%A, %B %-d, %Y"),
        "generated_at": today.strftime("%-I:%M %p %Z"),
        "rss_source_names": rss_source_names,
        "spiritual": spiritual,
        "weather": weather,
        "markets": markets,
        "at_a_glance": claude_output.get("at_a_glance", []),
        "youtube_videos": youtube_videos,
        "youtube_quiet_note": youtube_quiet_note,
        "youtube_channel_count": len(all_channels),
        "local_items": claude_output.get("local_items", []),
        "week_ahead": claude_output.get("week_ahead", []),
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
        fallback = Path(__file__).parent / "output" / "last_digest.html"
        fallback.parent.mkdir(exist_ok=True)
        fallback.write_text(html)
        log.info(f"Saved fallback to {fallback}")
        sys.exit(1)


if __name__ == "__main__":
    run()
