"""Stage: synthesize — Main synthesis pass via LLM.

Inputs:  raw_sources (dict), compressed_transcripts (list)
Outputs: synthesis_output (dict)

Builds the full synthesis prompt from all source data and calls the LLM.
The prompt and output format are preserved exactly from digest.py for Phase 0.
"""

import json
import logging
from datetime import datetime

from llm import call_llm
from validate import validate_stage_output

log = logging.getLogger(__name__)


def _group_rss_by_category(rss: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for item in rss:
        cat = item.get("category", "uncategorized")
        groups.setdefault(cat, []).append(item)
    return groups


def _fmt_calendar_events(events: list) -> str:
    if not events:
        return "None."
    lines = []
    for ev in events:
        iso = ev.get("date", "")
        try:
            d = datetime.strptime(iso, "%Y-%m-%d")
            date_label = d.strftime("%a %b %-d")
        except Exception:
            date_label = iso
        lines.append(f'{date_label}: {ev.get("event", "")}')
        if ev.get("description"):
            lines.append(f'  {ev["description"]}')
    return "\n".join(lines)


def build_synthesis_prompt(source_data: dict, config: dict, force_friday: bool = False) -> tuple[str, str]:
    """Build system + user prompt for the main synthesis pass."""
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
    # Use compressed transcripts if available (injected from compress stage output)
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

    rss_groups = _group_rss_by_category(rss)
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


def run(inputs: dict, config: dict, model_config: dict | None = None, force_friday: bool = False) -> dict:
    """Run the main synthesis pass and return synthesis_output artifact."""
    raw_sources = inputs.get("raw_sources", {})
    compressed_transcripts = inputs.get("compressed_transcripts", [])

    # Merge compressed transcripts back into source data for prompt building
    source_data = dict(raw_sources)
    if compressed_transcripts:
        source_data["analysis_transcripts"] = compressed_transcripts

    effective_config = model_config or {
        "provider": "fireworks",
        "model": config.get("llm", {}).get("model", "accounts/fireworks/models/kimi-k2p5"),
        "max_tokens": config.get("llm", {}).get("max_tokens", 12000),
        "temperature": config.get("llm", {}).get("temperature", 0.4),
    }

    system_prompt, user_content = build_synthesis_prompt(source_data, config, force_friday=force_friday)

    log.info("Stage: synthesize — calling LLM for main synthesis pass...")
    output = call_llm(
        system_prompt,
        user_content,
        effective_config,
        max_retries=2,
        json_mode=True,
        stream=True,
    )

    # Security Layer 3: validate output
    output = validate_stage_output(output, raw_sources, "synthesize")

    return {"synthesis_output": output}
