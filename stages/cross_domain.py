"""Stage: cross_domain — Editor-in-chief cross-domain synthesis pass.

This is the highest-order analytical stage in the pipeline. It reads all domain
analyses and seam data, discovers cross-domain connections the specialist desks
couldn't see from within their domains, selects and writes deep dives, and
produces the final editorial product.

The cross-domain stage does NOT rewrite domain analysis work. It:
  1. Discovers connections across domains via connection_hooks matching.
  2. Selects 1-3 deep dives from candidates flagged by domain passes.
  3. Writes deep dive body text that goes deeper than at-a-glance items.
  4. Adds cross_domain_note to at-a-glance items with multi-domain relevance.
  5. Enforces deduplication: each story appears in at most two sections.

Model selection: Best available model. This is the one stage where model quality
directly determines digest quality.

Inputs:  domain_analysis (dict), seam_data (dict), raw_sources (dict)
Outputs: cross_domain_output (dict) containing at_a_glance, deep_dives,
         cross_domain_connections, market_context
"""

import json
import logging
from datetime import datetime
from urllib.parse import urlparse

from llm import call_llm

log = logging.getLogger(__name__)

_VALID_TAGS = {"war", "domestic", "econ", "ai", "tech", "defense", "space", "cyber"}

_TAG_LABELS = {
    "war": "Conflict",
    "domestic": "Politics",
    "econ": "Economy",
    "ai": "AI",
    "tech": "Technology",
    "defense": "Defense",
    "space": "Space",
    "cyber": "Cyber",
}

# Keyword → standard tag mapping for post-processing normalization.
# Keys are lowercase substrings; first match wins.
_TAG_KEYWORDS: list[tuple[str, str]] = [
    # war / conflict
    ("iran", "war"),
    ("israel", "war"),
    ("ukraine", "war"),
    ("russia", "war"),
    ("military", "war"),
    ("combat", "war"),
    ("war", "war"),
    ("conflict", "war"),
    ("attack", "war"),
    ("strike", "war"),
    ("missile", "war"),
    ("troops", "war"),
    ("ceasefire", "war"),
    ("nato", "war"),
    ("hormuz", "war"),
    ("hostage", "war"),
    # defense
    ("defense", "defense"),
    ("pentagon", "defense"),
    ("f-35", "defense"),
    ("f-15", "defense"),
    ("procurement", "defense"),
    ("dod", "defense"),
    ("special forces", "defense"),
    ("recovery", "defense"),
    ("basing", "defense"),
    # space
    ("space", "space"),
    ("lunar", "space"),
    ("orbit", "space"),
    ("satellite", "space"),
    ("cislunar", "space"),
    ("launch", "space"),
    ("nasa", "space"),
    # ai
    ("ai", "ai"),
    ("llm", "ai"),
    ("artificial intelligence", "ai"),
    ("machine learning", "ai"),
    ("openai", "ai"),
    ("anthropic", "ai"),
    ("developer", "ai"),
    ("tooling", "ai"),
    ("model", "ai"),
    # tech
    ("tech", "tech"),
    ("software", "tech"),
    ("cyber", "cyber"),
    ("open source", "tech"),
    ("github", "tech"),
    # cyber
    ("cyber", "cyber"),
    ("hack", "cyber"),
    ("security breach", "cyber"),
    ("ransomware", "cyber"),
    ("malware", "cyber"),
    # econ
    ("econ", "econ"),
    ("market", "econ"),
    ("trade", "econ"),
    ("tariff", "econ"),
    ("inflation", "econ"),
    ("fed", "econ"),
    ("gdp", "econ"),
    ("labor", "econ"),
    ("wage", "econ"),
    ("energy", "econ"),
    ("oil", "econ"),
    ("food", "econ"),
    ("supply chain", "econ"),
    ("wto", "econ"),
    ("imf", "econ"),
    # domestic / politics
    ("trump", "domestic"),
    ("congress", "domestic"),
    ("senate", "domestic"),
    ("white house", "domestic"),
    ("election", "domestic"),
    ("domestic", "domestic"),
    ("administration", "domestic"),
    ("politics", "domestic"),
    ("gop", "domestic"),
]


def _normalize_tag(raw: str) -> str:
    """Map a raw LLM tag to the standard CSS vocabulary.

    Tries exact match first, then keyword scan, then falls back to 'domestic'.
    """
    normalized = raw.strip().lower()
    if normalized in _VALID_TAGS:
        return normalized
    for keyword, tag in _TAG_KEYWORDS:
        if keyword in normalized:
            return tag
    log.debug(f"cross_domain: unknown tag '{raw}' — defaulting to 'domestic'")
    return "domestic"


_SYSTEM_PROMPT = """You are the editor-in-chief of Aaron's Morning Digest. You receive domain analyses from four specialist desks (geopolitics, defense/space, AI/tech, economics) and a quality-control review from a seam detection analyst. Your job is NOT to rewrite their work — it's to find connections they couldn't see from within their domain, select the day's deep dives, and weave the pieces into a coherent editorial product.

VOICE: Write as an informed colleague — direct, analytical, occasionally wry. Use first person when offering interpretation. Use topic sentences. Never hedge with "it remains to be seen" or "only time will tell." Attribute uncertainty to specific actors ("analysts disagree on whether...") rather than to the abstract situation. Favor the structure: what happened → why it matters → what to watch for.

=== YOUR THREE TASKS ===

TASK 1: CROSS-DOMAIN CONNECTION DISCOVERY

Read all connection_hooks from the domain analyses. Look for:
- Causal chains: A development in one domain caused or will cause effects in another (a trade policy that changes a defense posture, an AI capability that shifts a geopolitical balance).
- Shared actors: The same entity (company, country, organization) appears in multiple domain analyses — what do their actions across domains tell you that no single domain reveals?
- Contradictions: One domain's analysis implies X while another's implies not-X. If the econ desk says a policy is stabilizing and the defense desk says it's destabilizing, that tension is the story.
- Second-order effects: A development in domain A that most people would see as contained within A actually has implications for domain B that the specialists didn't flag.

For each connection you find, add a cross_domain_note to the relevant at-a-glance item. Keep notes to 1-2 sentences. The note should say what the connection IS, not just that a connection exists.

TASK 2: DEEP DIVE SELECTION AND WRITING

Select 1-3 deep dives from the candidates flagged by domain passes. Prioritize:
1. Stories with cross-domain connections (these make the best dives because they reveal something no single domain saw).
2. Stories where seam detection found contested narratives or key assumption vulnerabilities.
3. Stories aligned with Aaron's primary interests: defense/space technology, AI implications for national security, geopolitical shifts affecting US posture.

For each selected deep dive, write a body (4-8 paragraphs in HTML) that:
- Does NOT repeat the at-a-glance facts and analysis — reference them and go deeper.
- Focuses on "what this connects to that isn't obvious from the headline."
- Uses the domain analysis's facts as foundation and builds the connective insight on top.
- Includes source attribution for all claims.
- Ends with specific indicators to watch ("If X happens, it means Y").
- Uses <p>, <em>, <strong> tags for structure. No <h1>-<h6> tags.

Also include 2-4 further_reading links drawn from the domain analysis links.

TASK 3: EDITORIAL ASSEMBLY

Produce the final at_a_glance list by:
- Taking all non-deep-dive items from all four domain analyses.
- Ordering by editorial importance: widely-reported stories first, then corroborated, then single-source. Within each tier, lead with stories that have cross-domain connections.
- Adding cross_domain_note where applicable.
- Capping at 7 items (quality over quantity — the editor will enforce this cap).

DEDUPLICATION RULES (critical):
- If a story appears as an at-a-glance item AND is selected for a deep dive: the at-a-glance entry keeps its original facts/analysis, and the deep dive must NOT repeat them. The deep dive adds the connective and deeper analysis only.
- If a story appears in seam detection (contested narrative): the at-a-glance item should note "See Perspective Seams for competing framings" rather than restating the contested framing.
- Each story appears in at most two sections. Each appearance must add distinct analytical value.
- Never say the same thing twice across sections.

=== OUTPUT FORMAT ===

JSON object:
{
  "at_a_glance": [
    {
      "tag": "MUST be exactly one of: war, domestic, econ, ai, tech, defense, space, cyber — no other values",
      "tag_label": "human-readable label matching the tag (e.g. war→Conflict, domestic→Politics, econ→Economy, ai→AI, tech→Technology, defense→Defense, space→Space, cyber→Cyber)",
      "headline": "from domain analysis (may be lightly edited for consistency)",
      "facts": "from domain analysis (preserved as-is)",
      "analysis": "from domain analysis (preserved as-is)",
      "source_depth": "single-source|corroborated|widely-reported",
      "cross_domain_note": "1-2 sentences on cross-domain connection, or null if none",
      "links": [{"url": "exact URL", "label": "Source Name"}],
      "connection_hooks": [{"entity": "...", "region": "...", "theme": "...", "policy": "..."}]
    }
  ],
  "deep_dives": [
    {
      "headline": "deep dive headline",
      "body": "<p>HTML body text, 4-8 paragraphs...</p>",
      "further_reading": [{"url": "exact URL", "label": "Source Name: Article Title"}],
      "source_depth": "from the original domain item",
      "domains_bridged": ["geopolitics", "defense_space"]
    }
  ],
  "cross_domain_connections": [
    {
      "description": "1-2 sentence description of the connection",
      "domains": ["domain_a", "domain_b"],
      "entities": ["shared entity names"],
      "theme": "thematic thread"
    }
  ],
  "market_context": "from econ domain analysis, preserved as-is",
  "worth_reading": [   // 3 long-form pieces worth slow reading today
    {
      "title": "article title",
      "url": "exact URL from sources",
      "source": "source name",
      "description": "2-3 sentence summary of why this piece is worth setting aside time for",
      "read_time": "estimated read time, e.g. '15 min read'"
    }
  ]
}

RULES:
- All URLs must come from the domain analysis links or raw source URLs — never fabricate.
- Preserve domain analysts' facts and analysis verbatim in at_a_glance items — your editorial contribution is the ordering, cross_domain_notes, and deep dive writing.
- If no stories warrant a deep dive, return an empty deep_dives array. Do not force one.
- cross_domain_connections is metadata for the briefing packet — include all connections you identified, even minor ones.
- TAG FIELD: use ONLY these exact values: war, domestic, econ, ai, tech, defense, space, cyber. No hyphens, no compound tags, no topic descriptions. Every at_a_glance item must have one of these eight values.
- Output ONLY valid JSON. No markdown fences, no commentary outside the JSON."""


def _build_input(
    domain_analysis: dict,
    seam_data: dict,
    raw_sources: dict,
    previous_cross_domain: dict | None = None,
    force_friday: bool = False,
) -> str:
    """Build the user content for the cross-domain synthesis prompt."""
    parts = []

    # Domain analyses
    parts.append("=== DOMAIN ANALYSES ===")
    for domain_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        items = domain_result.get("items", [])
        parts.append(f"\n--- {domain_key.upper()} ({len(items)} items) ---")
        parts.append(json.dumps(domain_result, indent=2))

    # Seam data
    parts.append("\n=== SEAM DETECTION RESULTS ===")
    parts.append(json.dumps(seam_data, indent=2))

    # Raw source URLs for reference (just titles + URLs, not full summaries)
    rss = raw_sources.get("rss", [])
    if rss:
        parts.append("\n=== SOURCE URL REFERENCE ===")
        parts.append("(Available URLs for linking — use only these)")
        for item in rss:
            if item.get("url"):
                parts.append(f"  {item.get('source', '?')}: {item.get('url', '')}")

    # Previous-day continuity
    if previous_cross_domain:
        prev_glance_headlines = [
            i.get("headline", "")
            for i in previous_cross_domain.get("at_a_glance", [])
            if i.get("headline")
        ]
        prev_dive_headlines = [
            d.get("headline", "")
            for d in previous_cross_domain.get("deep_dives", [])
            if d.get("headline")
        ]
        if prev_glance_headlines or prev_dive_headlines:
            parts.append(
                "\n=== CONTINUITY — Yesterday's digest included these stories ==="
            )
            if prev_glance_headlines:
                parts.append("At a glance: " + " | ".join(prev_glance_headlines))
            if prev_dive_headlines:
                parts.append("Deep dives: " + " | ".join(prev_dive_headlines))
            parts.append(
                "If any of today's stories are developments in these ongoing narratives, note "
                '"continuing from yesterday" or "new development" in your analysis field. '
                "Do NOT repeat yesterday's analysis — just acknowledge the thread. "
                "If none of today's stories connect to yesterday, ignore this section entirely."
            )

    # Always request worth_reading picks
    parts.append(
        "\n=== WORTH READING ===\n"
        "Select 3 substantial long-form pieces from the source data worth reading today. "
        "Prioritize depth, lasting relevance, and pieces that reward slow reading "
        "over breaking news. Include the worth_reading array in your JSON output."
    )

    parts.append(
        "\n\nPerform cross-domain synthesis: discover connections, select deep dives, "
        "assemble the editorial product. Output ONLY valid JSON."
    )
    return "\n".join(parts)


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Run cross-domain synthesis and return the editorial product."""
    domain_analysis = context.get("domain_analysis", {})
    seam_data = context.get("seam_data", {})
    raw_sources = context.get("raw_sources", {})

    effective_config = model_config or config.get("llm", {})

    # Check if we have domain analysis to work with
    has_items = any(
        isinstance(v, dict) and v.get("items") for v in domain_analysis.values()
    )
    if not has_items:
        log.warning("cross_domain: no domain analysis items — returning passthrough")
        return {"cross_domain_output": _empty_output(domain_analysis)}

    user_content = _build_input(
        domain_analysis,
        seam_data,
        raw_sources,
        context.get("previous_cross_domain"),
        force_friday=kwargs.get("force_friday", False),
    )

    try:
        log.info("Stage: cross_domain — running editor-in-chief synthesis...")
        result = call_llm(
            _SYSTEM_PROMPT,
            user_content,
            effective_config,
            max_retries=2,
            json_mode=True,
            stream=True,
        )
    except Exception as e:
        log.error(f"cross_domain: LLM call failed: {e}")
        return {"cross_domain_output": _empty_output(domain_analysis)}

    # Normalize result
    if not isinstance(result, dict):
        log.warning("cross_domain: LLM returned non-dict, falling back to passthrough")
        return {"cross_domain_output": _empty_output(domain_analysis)}

    # Ensure required fields
    result.setdefault("at_a_glance", [])
    result.setdefault("deep_dives", [])
    result.setdefault("cross_domain_connections", [])
    result.setdefault("worth_reading", [])
    if "market_context" not in result:
        econ = domain_analysis.get("econ", {})
        result["market_context"] = econ.get("market_context", "")

    # Build the set of known source domains for URL validation.
    # Domain-level matching (not exact URL) allows the LLM to reference real articles
    # even when URL format differs slightly from what was ingested (UTM params, etc.).
    known_urls: set[str] = set()
    for item in raw_sources.get("rss", []):
        if item.get("url"):
            known_urls.add(item["url"])
    for item in raw_sources.get("local_news", []):
        if item.get("url"):
            known_urls.add(item["url"])
    for t in raw_sources.get("analysis_transcripts", []):
        if t.get("url"):
            known_urls.add(t["url"])
    known_domains: set[str] = {
        urlparse(u).netloc for u in known_urls if urlparse(u).netloc
    }

    def _url_allowed(url: str) -> bool:
        return not url or urlparse(url).netloc in known_domains

    # Normalize tags to the standard vocabulary
    for item in result["at_a_glance"]:
        item["tag"] = _normalize_tag(item.get("tag", ""))
        item["tag_label"] = _TAG_LABELS.get(item["tag"], item.get("tag_label", ""))

    # Validate URLs in at_a_glance, deep_dives, and worth_reading
    for item in result["at_a_glance"]:
        item["links"] = [
            lnk for lnk in item.get("links", []) if _url_allowed(lnk.get("url", ""))
        ]
    for dive in result["deep_dives"]:
        dive["further_reading"] = [
            lnk
            for lnk in dive.get("further_reading", [])
            if _url_allowed(lnk.get("url", ""))
        ]
    for read in result["worth_reading"]:
        if not _url_allowed(read.get("url", "")):
            read["url"] = ""

    # Enforce at-a-glance item cap from config
    digest_cfg = config.get("digest", {})
    glance_cfg = digest_cfg.get("at_a_glance", {})
    max_items = glance_cfg.get("max_items", 7)
    if len(result["at_a_glance"]) > max_items:
        # Sort by source_depth priority, then by cross_domain_note presence
        depth_priority = {"widely-reported": 0, "corroborated": 1, "single-source": 2}
        result["at_a_glance"].sort(
            key=lambda i: (
                depth_priority.get(i.get("source_depth", ""), 3),
                0 if i.get("cross_domain_note") else 1,
            )
        )
        dropped = result["at_a_glance"][max_items:]
        result["at_a_glance"] = result["at_a_glance"][:max_items]
        log.info(
            f"  cross_domain: capped at_a_glance from {max_items + len(dropped)} "
            f"to {max_items} items (dropped {len(dropped)} lower-priority items)"
        )

    n_glance = len(result["at_a_glance"])
    n_dives = len(result["deep_dives"])
    n_connections = len(result["cross_domain_connections"])
    log.info(
        f"  cross_domain: {n_glance} at-a-glance, {n_dives} deep dives, "
        f"{n_connections} cross-domain connections"
    )

    return {"cross_domain_output": result}


def _empty_output(domain_analysis: dict) -> dict:
    """Build a passthrough output when cross-domain synthesis can't run.

    Falls back to the simple merge logic that assemble.py used in Phase 1.
    """
    all_items = []
    market_context = ""
    for domain_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        if domain_key == "econ" and domain_result.get("market_context"):
            market_context = domain_result["market_context"]
        for item in domain_result.get("items", []):
            all_items.append(item)

    # Separate deep dive candidates
    at_a_glance = [i for i in all_items if not i.get("deep_dive_candidate")]
    dive_candidates = [i for i in all_items if i.get("deep_dive_candidate")]

    # Simple deep dive conversion
    deep_dives = []
    for item in dive_candidates[:3]:
        body_parts = []
        if item.get("facts"):
            body_parts.append(f"<p>{item['facts']}</p>")
        if item.get("analysis"):
            body_parts.append(f"<p>{item['analysis']}</p>")
        if item.get("deep_dive_rationale"):
            body_parts.append(
                f"<p><em>Why this matters: {item['deep_dive_rationale']}</em></p>"
            )
        deep_dives.append(
            {
                "headline": item.get("headline", ""),
                "body": "\n".join(body_parts),
                "further_reading": item.get("links", []),
                "source_depth": item.get("source_depth", ""),
                "domains_bridged": [],
            }
        )

    return {
        "at_a_glance": at_a_glance,
        "deep_dives": deep_dives,
        "cross_domain_connections": [],
        "market_context": market_context,
    }
