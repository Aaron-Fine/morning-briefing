#!/usr/bin/env python3
"""Morning Digest — main orchestrator.

Collects data from all configured sources, sends it to Claude for synthesis
and editorial judgment, renders the HTML email, and sends it.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path

import openai
import yaml

from sources.youtube import fetch_analysis_transcripts
from sources.weather import fetch_weather
from sources.markets import fetch_markets
from sources.launches import fetch_upcoming_launches
from sources.rss_feeds import fetch_rss
from sources.come_follow_me import get_current_lesson, get_upcoming_church_events
from sources.holidays import get_upcoming_holidays
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

    # Upcoming space launches
    log.info("  → Space launches")
    data["launches"] = fetch_upcoming_launches()

    # Upcoming church events
    data["church_events"] = get_upcoming_church_events()

    # Upcoming holidays
    data["holidays"] = get_upcoming_holidays(days=10)

    # Come Follow Me
    if config.get("digest", {}).get("spiritual", {}).get("enabled", True):
        log.info("  → Come Follow Me")
        data["come_follow_me"] = get_current_lesson(config)

    # YouTube analysis transcripts
    log.info("  → YouTube analysis channels")
    try:
        data["analysis_transcripts"] = fetch_analysis_transcripts(config)
    except Exception as e:
        log.warning(f"  YouTube analysis failed: {e}")
        data["analysis_transcripts"] = []

    # RSS feeds
    log.info("  → RSS feeds")
    data["rss"] = fetch_rss(config)

    # Local news (separate from main RSS so Claude can distinguish them)
    local_sources = config.get("local_news", {}).get("sources", [])
    if local_sources:
        log.info("  → Local news")
        local_rss_config = {"rss": {"feeds": local_sources, "provider": "direct"}}
        data["local_news"] = fetch_rss(local_rss_config)
    else:
        data["local_news"] = []

    # Source counts
    data["source_counts"] = {
        "analysis_transcripts": len(data.get("analysis_transcripts", [])),
        "rss_items": len(data.get("rss", [])),
        "local_news_items": len(data.get("local_news", [])),
    }

    log.info(
        f"  Collected: {data['source_counts']['rss_items']} RSS items, "
        f"{data['source_counts']['local_news_items']} local news items, "
        f"{data['source_counts']['analysis_transcripts']} analysis transcripts"
    )
    return data


def _group_rss_by_category(rss: list[dict]) -> dict[str, list[dict]]:
    """Group RSS items by their category field for tiered treatment."""
    groups: dict[str, list[dict]] = {}
    for item in rss:
        cat = item.get("category", "uncategorized")
        groups.setdefault(cat, []).append(item)
    return groups


def build_synthesis_prompt(source_data: dict, config: dict, force_friday: bool = False) -> tuple[str, str]:
    """Build the system + user prompt for the main synthesis pass (Stage 2).

    Sources are grouped by category for tiered editorial treatment.
    """
    today = datetime.now()
    is_friday = force_friday or today.weekday() == 4
    date_display = today.strftime("%A, %B %-d, %Y")

    cfm = source_data.get("come_follow_me", {})
    weather = source_data.get("weather", {})
    markets = source_data.get("markets", [])
    launches = source_data.get("launches", [])
    church_events = source_data.get("church_events", [])
    holidays = source_data.get("holidays", [])
    rss = source_data.get("rss", [])
    analysis_transcripts = source_data.get("analysis_transcripts", [])

    weekend_reads_schema = ""
    if is_friday:
        weekend_reads_schema = """  "weekend_reads": [
    {{"url": "...", "title": "...", "source": "...", "read_time": "~N min", "description": "1 sentence pitch"}}
  ],"""

    system_prompt = f"""You are the editor of Aaron's Morning Digest, a daily email briefing.
Your voice is that of an informed colleague — direct, analytical, occasionally wry. Never newscaster.
Never blog-post. Think Philip DeFranco's story selection instincts crossed with Belle of the Ranch's
"medium dive" depth on carefully selected topics.

Today is {date_display}. Aaron lives in Providence, Utah (Cache Valley), a suburb of Logan, Utah.

OUTPUT FORMAT: You must respond with a single valid JSON object (no markdown fencing, no preamble).
The JSON must match this exact structure:

{{
  "at_a_glance": [
    {{
      "tag": "war|ai|domestic|defense|space|tech|local|science|econ|cyber",
      "tag_label": "War|AI|US|Defense|Space|Tech|Local|Science|Econ|Cyber",
      "headline": "short headline",
      "context": "3-5 sentences of analytical context — this is where the value lives",
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
  "local_items": [
    {{"headline": "USU wins conference title", "url": "https://www.cachevalleydaily.com/sports/article_abc.html", "context": "Utah State men's basketball claimed the Mountain West title Saturday."}}
  ],
  "week_ahead": [
    {{"date": "Wed Mar 26", "event": "SpaceX Falcon 9 Starlink launch from Vandenberg"}},
    {{"date": "Sat Apr 4", "event": "LDS General Conference — Saturday sessions"}}
  ],
  "market_context": "Defense ETF XAR rose 1.2% as Congress advanced the DoD supplemental spending bill covered above.",
  "spiritual_reflection": "2-3 sentences connecting this week's scripture study lesson to today's world. Thoughtful, not preachy.",
{weekend_reads_schema}
}}

RULES:
- At a Glance: {config['digest']['at_a_glance']['normal_items']} items on a normal day, up to {config['digest']['at_a_glance']['max_items']} on busy days, minimum {config['digest']['at_a_glance']['min_items']}
- At a Glance context: This is where the digest earns its keep. Write 3-5 sentences per item that
  synthesize across sources, note divergent framing when relevant, and connect to broader patterns.
  Don't just restate the headline — explain WHY this matters, WHAT it connects to, and WHERE different
  sources disagree. If a non-western source frames the same event differently from a western one,
  note that in the context. This is analytical briefing, not a wire service summary.
- Deep Dives: exactly {config['digest']['deep_dives']['count']}, with Further Reading links (1-2 per dive)
- Skip celebrity gossip and internet drama unless linked to a topic discussed elsewhere
- Tags: war (conflicts/geopolitics), ai (AI/LLMs/agentic), domestic (US politics/policy), defense (DoD/missile/military), space (launches/satellites/exploration), tech (self-hosting/EVs/consumer tech/open source), local (Cache Valley/Utah), science (research/applied science), econ (economics/trade/macro), cyber (cybersecurity)
- Primary topics: {', '.join(config['topics']['primary'])}
- Secondary topics: {', '.join(config['topics']['secondary'])}
- Tertiary topics: {', '.join(config['topics']['tertiary'])}
- Professional context: DoD / Dept of War, missile warning/defense, UARC/FFRDC, space technology, software engineering, systems engineering.
- Local items: Cache Valley focus, max {config['digest']['local']['max_items']} items. Use the LOCAL NEWS section as your source — do not fabricate. Each item is an object with "headline", "url" (copy the exact URL from the source article), and "context" (1-2 sentence summary). Omit entirely if nothing qualifies.
- Week ahead: up to {config['digest']['week_ahead']['count']} upcoming events. Draw from the UPCOMING LAUNCHES & EVENTS section — copy the date string verbatim as it appears there (e.g. "Wed Mar 26", "Sat Apr 4"). Never abbreviate to just a weekday name without the month and day. Prioritize consequential or personally relevant events. Do not infer or invent.
- Market context: If any market move (≥ 0.5% up or down) connects meaningfully to a story covered in today's digest, include "market_context" with 1-2 sentences explaining the connection. Otherwise omit this field.
- Deep dive body uses <p> tags for paragraphs
- All URLs in output must come from the source data below — never fabricate URLs
- It is better to leave out a section entirely than to make up data for it. If a section has no relevant source data, omit it or return an empty array.
{"- Include weekend_reads: 3 long-form pieces worth setting aside time for this weekend. URLs must come from source data." if is_friday else "- This is not Friday, so omit weekend_reads from the JSON."}

SOURCE TREATMENT BY CATEGORY (each source has a "category" field):
- "non-western": Non-Western English-language outlets (Al Jazeera, SCMP, Nikkei, Hindu, Dawn, Asia Times).
  Compare their framing against other coverage. When their framing diverges significantly from Western
  sources on the same event, note the divergence in context. Compress overlap but preserve divergent angles.
- "western-analysis": Western independent analysis (The Atlantic). Use for interpretation and framing —
  the "what it means" layer alongside factual reporting.
- "substack-independent": Independent analyst newsletters (Chartbook, China Talk, Drezner, etc.).
  Treat as the "what it means" interpretation layer. These provide context and framing but should not
  drive story selection alone without corroboration from harder journalism.
- "defense-mil": Defense and military specialist feeds. Use for domain depth on defense, space, and
  military topics. These are more relevant when they report substantive developments.
- "ai-tech": AI and technology sources. Treat as specialist analysis on AI topics.
- "econ-trade": Economics and trade mechanics. Surface when relevant to geopolitics or policy.
- "global-south": Africa, Latin America, developing world coverage. Only surface when they cover stories
  missing from Western sources, or when their framing contradicts the Western consensus.
- "perspective-diversity": Sources included for viewpoint stress-testing (The Diff, Slow Boring).
  Do NOT summarize routinely — only surface when they offer a take that contradicts the consensus
  of the other sources. These are the "stress test" layer.
- "youtube-analysis": Pre-compressed YouTube analysis transcripts. Treat as independent analysis inputs.
  Attribute to the channel name. Use the same editorial treatment as substack-independent.
- "cyber": Cybersecurity feeds. Surface notable incidents, vulnerabilities, or policy developments.

COMPRESSION RULES:
- Multiple sources covering the same event: merge into one At a Glance item with multiple source links.
  Prefer the most specific or best-sourced version as the backbone.
- Items with "tag": "compress": AI-generated newsletters. Extract ONLY concrete facts, product names,
  data points. Strip all framing, rhetorical questions, and hype. Target 3 to 7 bullet-worthy facts.
- Substack posts that are primarily link roundups (vs. original analysis): compress aggressively,
  extract only novel facts not available from harder sources.
- Non-Western overlap with other coverage on the same story: compress, BUT preserve any divergent
  framing as a parenthetical or note in the context field.
"""

    local_news = source_data.get("local_news", [])

    # Pre-format calendar events with explicit date strings so the model copies them verbatim
    def _fmt_calendar_events(events: list) -> str:
        if not events:
            return "None."
        lines = []
        for ev in events:
            iso = ev.get("date", "")
            try:
                d = datetime.strptime(iso, "%Y-%m-%d")
                date_label = d.strftime("%a %b %-d")  # e.g. "Sat Apr 4"
            except Exception:
                date_label = iso
            lines.append(f'{date_label}: {ev.get("event", "")}')
            if ev.get("description"):
                lines.append(f'  {ev["description"]}')
        return "\n".join(lines)

    # Group RSS items by category for structured presentation
    rss_groups = _group_rss_by_category(rss)

    # Build category-grouped RSS section
    rss_sections = []
    category_order = [
        "non-western", "western-analysis", "defense-mil", "substack-independent",
        "ai-tech", "econ-trade", "global-south", "perspective-diversity", "cyber",
        "uncategorized",
    ]
    total_rss = 0
    for cat in category_order:
        items = rss_groups.get(cat, [])
        if not items:
            continue
        # Cap total items to prevent context overflow
        remaining = 100 - total_rss
        if remaining <= 0:
            break
        display_items = items[:remaining]
        total_rss += len(display_items)
        rss_sections.append(
            f'--- {cat.upper()} ({len(display_items)} items) ---\n'
            f'{json.dumps(display_items, indent=2)}'
        )

    rss_block = "\n\n".join(rss_sections) if rss_sections else "No RSS items available."

    # Build analysis transcripts section
    transcript_block = ""
    if analysis_transcripts:
        transcript_items = []
        for t in analysis_transcripts:
            transcript_items.append({
                "channel": t["channel"],
                "title": t["title"],
                "url": t["url"],
                "category": t.get("category", "youtube-analysis"),
                "compressed_transcript": t.get("compressed_transcript", ""),
            })
        transcript_block = json.dumps(transcript_items, indent=2)

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

=== UPCOMING LAUNCHES & EVENTS (next 10 days — copy these date strings verbatim into week_ahead output) ===
{_fmt_calendar_events(launches + church_events + holidays)}

=== RSS / NEWS ({total_rss} items, grouped by source category) ===
{rss_block}

=== ANALYSIS TRANSCRIPTS (pre-compressed YouTube, {len(analysis_transcripts)} videos) ===
{transcript_block if transcript_block else "No analysis transcripts available."}

=== LOCAL NEWS ({len(local_news)} items) ===
{json.dumps(local_news, indent=2) if local_news else "No local news items available."}

Remember: output ONLY valid JSON, no markdown fencing, no commentary outside the JSON.
"""

    return system_prompt, user_content


def call_llm(
    system_prompt: str,
    user_content: str,
    config: dict,
    max_retries: int = 2,
    llm_override: dict | None = None,
    json_mode: bool = True,
    stream: bool = True,
) -> dict | str:
    """Send prompt to the LLM and return the parsed response.

    Args:
        llm_override: dict with model/max_tokens/temperature overrides.
        json_mode: if True, request JSON output and parse it. If False, return raw text.
        stream: if True, use streaming (better for long responses). If False, use
                a single request (more reliable for shorter responses like compression).

    Retries on transient errors with exponential backoff.
    """
    client = openai.OpenAI(
        api_key=os.environ["FIREWORKS_API_KEY"],
        base_url="https://api.fireworks.ai/inference/v1",
    )

    llm_config = config.get("llm", {})
    if llm_override:
        llm_config = {**llm_config, **llm_override}
    model = llm_config.get("model", "accounts/fireworks/models/kimi-k2p5")
    max_tokens = llm_config.get("max_tokens", 12000)
    temperature = llm_config.get("temperature", 0.3)

    create_kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    if json_mode:
        create_kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait = 2 ** attempt * 5  # 10s, 20s
                log.info(f"Retrying in {wait}s (attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait)

            log.info(f"Calling LLM ({model})...")

            if stream:
                create_kwargs["stream"] = True
                chunks = []
                with client.chat.completions.create(**create_kwargs) as resp:
                    for chunk in resp:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta.content
                        if delta:
                            chunks.append(delta)
                raw = "".join(chunks).strip()
            else:
                create_kwargs["stream"] = False
                resp = client.chat.completions.create(**create_kwargs)
                raw = (resp.choices[0].message.content or "").strip()

            break
        except openai.APIStatusError as e:
            log.warning(f"LLM API error: {e}")
            if attempt == max_retries or e.status_code < 500:
                raise
        except openai.APIConnectionError as e:
            log.warning(f"LLM connection error: {e}")
            if attempt == max_retries:
                raise

    if not json_mode:
        return raw

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse LLM response as JSON: {e}")
        log.error(f"Raw response (first 500 chars): {raw[:500]}")
        raise


def compress_transcripts(transcripts: list[dict], config: dict) -> list[dict]:
    """Stage 1: Pre-compress YouTube analysis transcripts via LLM.

    Runs one API call per video in parallel. Returns the same list with
    'transcript' replaced by 'compressed_transcript'.
    """
    if not transcripts:
        return transcripts

    compression_config = config.get("llm", {}).get("compression", {})

    system_prompt = (
        "You are a transcript compressor. Given a YouTube video transcript, "
        "produce a dense summary that preserves:\n"
        "1. All concrete claims and factual assertions\n"
        "2. The speaker's analytical framework and conclusions\n"
        "3. Any named sources, data points, or specific examples\n"
        "4. The speaker's specific interpretive framing — how they characterize events "
        "matters as much as what events they cover\n\n"
        "Strip: filler, repetition, sponsor/ad reads, calls to action, tangents, "
        "conversational padding, verbal tics.\n\n"
        "Target: 400-800 words output regardless of input length. "
        "Output plain text, no JSON, no markdown headers."
    )

    def _compress_one(video: dict) -> dict:
        transcript = video.get("transcript", "")
        if not transcript:
            return video

        user_content = (
            f"Channel: {video['channel']}\n"
            f"Video: {video['title']}\n"
            f"Transcript ({len(transcript)} chars):\n\n"
            f"{transcript}"
        )

        compressed = ""
        try:
            compressed = call_llm(
                system_prompt,
                user_content,
                config,
                max_retries=1,
                llm_override=compression_config,
                json_mode=False,
                stream=False,
            )
        except Exception as e:
            log.warning(f"  Compression failed for {video['title']}: {e}")

        # Retry once if empty (API sometimes returns empty under load)
        if not compressed.strip():
            log.info(f"  Empty response for {video['title']}, retrying...")
            time.sleep(2)
            try:
                compressed = call_llm(
                    system_prompt,
                    user_content,
                    config,
                    max_retries=1,
                    llm_override=compression_config,
                    json_mode=False,
                )
            except Exception as e:
                log.warning(f"  Compression retry failed for {video['title']}: {e}")

        # Final fallback: first ~600 words of raw transcript
        if not compressed.strip():
            log.warning(f"  Using raw fallback for {video['title']}")
            words = transcript.split()[:600]
            compressed = " ".join(words)
        else:
            log.info(
                f"  Compressed {video['channel']}: {video['title']} "
                f"({len(transcript)} → {len(compressed)} chars)"
            )

        result = {k: v for k, v in video.items() if k != "transcript"}
        result["compressed_transcript"] = compressed
        result["category"] = "youtube-analysis"
        return result

    log.info(f"Compressing {len(transcripts)} transcript(s) serially...")
    results = []
    for video in transcripts:
        results.append(_compress_one(video))
    return results


def detect_seams(
    synthesis_output: dict, source_data: dict, config: dict
) -> dict:
    """Stage 3: Detect narrative disagreements and coverage gaps.

    Runs on already-synthesized output. Returns dict with
    'contested_narratives' and 'coverage_gaps' lists.
    Non-fatal: returns empty results on failure.
    """
    seam_config = config.get("llm", {}).get("seam_detection", {})

    system_prompt = """You are a media analysis assistant. You will receive a synthesized news digest
(At a Glance items and Deep Dives) plus a summary of which source categories covered which stories.

Your job is to identify:

1. CONTESTED NARRATIVES: Stories where different source categories framed the same event differently.
   Example: one set of sources reports X as routine, while another frames it as alarming.
   Only flag genuine disagreements in framing, interpretation, or emphasis — not minor wording differences.

2. COVERAGE GAPS: Stories that appeared in some source categories but were absent from others.
   Only flag substantive omissions where the absence is itself informative.

RULES:
- Do NOT resolve disagreements or declare which framing is correct.
- Do NOT editorialize. State what each side says, neutrally.
- Your job is to make the disagreement visible, not to adjudicate it.
- Weight toward structural/framing disagreements rather than simple factual disputes.
- Maximum 3 contested narratives and 3 coverage gaps. Return fewer if fewer qualify.
- If nothing qualifies, return empty arrays.

OUTPUT FORMAT: JSON object:
{
  "contested_narratives": [
    {
      "topic": "short topic label",
      "description": "2-5 sentences describing the disagreement",
      "sources_a": "which sources/categories frame it one way",
      "sources_b": "which sources/categories frame it differently",
      "links": [{"url": "https://...", "label": "Outlet Name"}]
    }
  ],
  "coverage_gaps": [
    {
      "topic": "short topic label",
      "description": "2-5 sentences describing what was covered and by whom",
      "present_in": "source categories that covered it",
      "absent_from": "source categories that did not",
      "links": [{"url": "https://...", "label": "Outlet Name"}]
    }
  ]
}

LINK RULES:
- For each seam item, include 1-2 links to specific articles from the AT A GLANCE or DEEP DIVES data that illustrate the divergence or gap.
- Only use URLs that appear verbatim in the AT A GLANCE links or DEEP DIVES further_reading sections above — never fabricate URLs.
- If no relevant URL is available, omit the links array entirely but clearly state where the information came from."""

    # Build a category coverage map from raw RSS data
    rss = source_data.get("rss", [])
    category_coverage = {}
    for item in rss:
        cat = item.get("category", "uncategorized")
        category_coverage.setdefault(cat, []).append(item.get("title", ""))
    # Include analysis transcripts
    for t in source_data.get("analysis_transcripts", []):
        category_coverage.setdefault("youtube-analysis", []).append(
            f"{t['channel']}: {t['title']}"
        )

    coverage_summary = "\n".join(
        f"- {cat}: {', '.join(titles[:10])}"
        for cat, titles in category_coverage.items()
        if titles
    )

    user_content = f"""Here is today's synthesized digest output:

=== AT A GLANCE ===
{json.dumps(synthesis_output.get('at_a_glance', []), indent=2)}

=== DEEP DIVES ===
{json.dumps(synthesis_output.get('deep_dives', []), indent=2)}

=== SOURCE CATEGORY COVERAGE MAP ===
(Which source categories had stories about which topics)
{coverage_summary}

Identify contested narratives and coverage gaps. Output ONLY valid JSON."""

    try:
        log.info("Running seam detection (Stage 3)...")
        result = call_llm(
            system_prompt,
            user_content,
            config,
            max_retries=1,
            llm_override=seam_config,
        )
        cn = result.get("contested_narratives", [])
        cg = result.get("coverage_gaps", [])
        log.info(f"  Seam detection: {len(cn)} contested narratives, {len(cg)} coverage gaps")
        return result
    except Exception as e:
        log.warning(f"Seam detection failed (non-fatal): {e}")
        return {"contested_narratives": [], "coverage_gaps": []}


def assemble_template_data(
    claude_output: dict, seam_data: dict, source_data: dict, config: dict
) -> dict:
    """Merge synthesis output + seam data with raw source data for template rendering."""
    today = datetime.now()

    weather = source_data.get("weather", {})
    markets = source_data.get("markets", [])
    cfm = source_data.get("come_follow_me", {})

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
    yt_names = [c["name"] for c in config.get("youtube", {}).get("analysis_channels", [])]
    all_source_names = rss_names + local_names
    rss_source_names = ", ".join(all_source_names) if all_source_names else "RSS feeds"
    yt_source_names = ", ".join(yt_names) if yt_names else ""

    return {
        "date_display": today.strftime("%A, %B %-d, %Y"),
        "generated_at": today.strftime("%-I:%M %p") + " " + config.get("location", {}).get("timezone", "America/Denver").split("/")[-1],
        "rss_source_names": rss_source_names,
        "yt_source_names": yt_source_names,
        "spiritual": spiritual,
        "weather": weather,
        "markets": markets,
        "at_a_glance": claude_output.get("at_a_glance", []),
        "contested_narratives": seam_data.get("contested_narratives", []),
        "coverage_gaps": seam_data.get("coverage_gaps", []),
        "local_items": claude_output.get("local_items", []),
        "market_context": claude_output.get("market_context", ""),
        "week_ahead": claude_output.get("week_ahead", []),
        "weekend_reads": claude_output.get("weekend_reads", []),
        "deep_dives": claude_output.get("deep_dives", []),
    }


def run(
    dry_run: bool = False,
    sources_only: bool = False,
    force_friday: bool = False,
    lookback_hours: int | None = None,
):
    """Main entry point.

    dry_run: collect sources, call Claude, render HTML, save to output/ — skip email.
    sources_only: collect sources and dump to output/sources.json — skip Claude and email.
    force_friday: force Friday mode (weekend reads) regardless of actual day.
    lookback_hours: override YouTube lookback_hours config.
    """
    log.info("=== Morning Digest starting ===")

    config = load_config()

    # Apply CLI overrides to config
    if lookback_hours is not None:
        config.setdefault("youtube", {})["lookback_hours"] = lookback_hours
        log.info(f"  Override: lookback_hours={lookback_hours}")
    if force_friday:
        log.info("  Override: forcing Friday mode")
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    # 1. Collect raw data from all sources
    source_data = collect_sources(config)

    if sources_only:
        out = output_dir / "sources.json"
        out.write_text(json.dumps(source_data, indent=2, default=str))
        log.info(f"=== Sources written to {out} ===")
        return

    # 2. Stage 1: Compress analysis transcripts
    transcripts = source_data.get("analysis_transcripts", [])
    if transcripts:
        log.info(f"Stage 1: Compressing {len(transcripts)} transcript(s)...")
        source_data["analysis_transcripts"] = compress_transcripts(transcripts, config)

    # 3. Stage 2: Main synthesis with tiered source treatment
    log.info("Stage 2: Main synthesis...")
    system_prompt, user_content = build_synthesis_prompt(source_data, config, force_friday=force_friday)
    claude_output = call_llm(system_prompt, user_content, config)

    # 4. Stage 3: Seam detection
    seam_data = detect_seams(claude_output, source_data, config)

    # 5. Assemble template data
    template_data = assemble_template_data(claude_output, seam_data, source_data, config)

    # 4. Render HTML
    html = render_email(template_data)

    if dry_run:
        out = output_dir / "last_digest.html"
        out.write_text(html)
        log.info(f"=== Dry run complete — digest saved to {out} ===")
        return

    # 5. Send email
    success = send_digest(html, config)

    if success:
        log.info("=== Digest sent successfully ===")
    else:
        log.error("=== Digest send FAILED ===")
        fallback = output_dir / "last_digest.html"
        fallback.write_text(html)
        log.info(f"Saved fallback to {fallback}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Morning Digest generator")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run full pipeline but save HTML to output/ instead of sending email")
    parser.add_argument("--sources-only", action="store_true",
                        help="Collect sources and dump to output/sources.json, skip Claude and email")
    parser.add_argument("--force-friday", action="store_true",
                        help="Force Friday mode (weekend reads, etc.) regardless of actual day")
    parser.add_argument("--lookback-hours", type=int, default=None,
                        help="Override YouTube lookback_hours (e.g. 120 to catch older videos)")
    args = parser.parse_args()
    run(
        dry_run=args.dry_run,
        sources_only=args.sources_only,
        force_friday=args.force_friday,
        lookback_hours=args.lookback_hours,
    )
