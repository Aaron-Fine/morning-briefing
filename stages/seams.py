"""Stage: seams — Detect narrative disagreements, coverage gaps, and key assumptions.

Phase 2 seam detection operates on domain analysis artifacts AND raw source data,
not just synthesized output. This gives it access to source-level framing that the
domain analysis passes may have smoothed over.

Three detection modes (all in one LLM call):
  1. Contested Narratives — where source categories frame the same event differently
  2. Coverage Gaps — stories present in some categories but absent from analyses
  3. Key Assumptions Check — IC-style identification of unstated analytical assumptions

The seam detection model should have DIFFERENT training biases than the domain
analysis model (Kimi K2.5) to provide bias diversity. Default: Claude Sonnet.

Inputs:  domain_analysis (dict), raw_sources (dict), compressed_transcripts (list)
Outputs: seam_data (dict)

Non-critical: returns empty results on failure so the pipeline can continue.
"""

import logging

from llm import call_llm
from validate import validate_urls

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior intelligence analyst performing quality control on a morning news digest. You are NOT the analyst who wrote the digest — you are reviewing their work with fresh eyes, looking for what they missed, where they smoothed over disagreements, and where their conclusions rest on unstated assumptions.

Your purpose is adversarial review: find the seams, gaps, and weak points in the analytical product you're reviewing. This is a feature of the editorial process, not a bug. Good analysis survives scrutiny.

You will receive:
1. DOMAIN ANALYSES: The analytical output from four specialist desks (geopolitics, defense/space, AI/tech, economics). These are the products you're reviewing.
2. RAW SOURCE DATA: The original source material the analysts had access to. Compare what sources actually said against what the analysts chose to present.
3. DEEP DIVE CANDIDATES: Stories flagged for extended treatment. Your key assumptions check focuses on these.

You perform three detection tasks:

=== TASK 1: CONTESTED NARRATIVES ===

Identify stories where different source categories framed the same event with genuinely different interpretive lenses. You have access to the raw source summaries — use them to find framing divergences that the domain analysis may have papered over by picking one framing.

Criteria:
- The disagreement must be about framing, interpretation, or emphasis — not minor factual differences.
- Both framings must be defensible (not one side being obviously wrong).
- The divergence should matter for the reader's understanding — a framing difference that changes the "so what" is more important than one that doesn't.
- Weight structural disagreements (different models of what's happening) over surface-level disagreements (different adjectives for the same assessment).

What to flag: "Source category A frames this as X, while source category B frames this as Y." Present both framings with attribution. Do NOT resolve the disagreement — making the divergence visible IS the analytical product.

=== TASK 2: COVERAGE GAPS ===

Identify substantive stories that appeared in the raw source data but were absent from or underweighted in the domain analyses. The omissions are often more interesting than what was included.

Criteria:
- The story must be substantive — not every RSS item deserves mention.
- The absence must be informative: a defense story missing from the defense analysis is notable; a celebrity gossip item missing from the geopolitics analysis is not.
- Stories that appeared in multiple source categories but weren't picked up by ANY domain analysis are the strongest gaps.
- A story covered by non-western sources but absent from the analysis may indicate a Western-media blind spot (and vice versa).

What to flag: "This story appeared in [categories] but was not included in the [domain] analysis. This matters because..."

=== TASK 3: KEY ASSUMPTIONS CHECK ===

For each deep dive candidate identified by the domain analyses, identify 1-2 key assumptions that must be true for the analysis to hold. This is standard IC tradecraft — every analytical judgment rests on assumptions, and making them explicit is how you avoid surprise.

Criteria:
- The assumption must be something the analysis takes for granted without stating it.
- The invalidator must be a specific, observable development (not "things could change").
- The confidence level should reflect how well-supported the assumption is, not how important it is.
- Focus on assumptions where the analyst might be wrong — not on uncontroversial background facts.

What to flag: "The analysis assumes [X]. If [specific development] occurs, this analysis breaks down. Current confidence in the assumption: [high/medium/low] because [brief reason]."

=== OUTPUT FORMAT ===

JSON object:
{
  "contested_narratives": [
    {
      "topic": "short topic label",
      "description": "3-5 sentences describing the framing divergence. Present both sides with attribution. Do not resolve.",
      "sources_a": "source categories/outlets framing it one way",
      "sources_b": "source categories/outlets framing it differently",
      "analytical_significance": "1 sentence on why this divergence matters for the reader",
      "links": [{"url": "https://...", "label": "Outlet Name"}]
    }
  ],
  "coverage_gaps": [
    {
      "topic": "short topic label",
      "description": "2-4 sentences describing what was covered, by whom, and why the gap matters",
      "present_in": "source categories that covered it",
      "absent_from": "domain analyses or source categories that did not",
      "links": [{"url": "https://...", "label": "Outlet Name"}]
    }
  ],
  "key_assumptions": [
    {
      "topic": "short topic label matching the deep dive candidate",
      "assumption": "what must be true for the analysis to hold",
      "invalidator": "specific observable development that would prove this wrong",
      "confidence": "high|medium|low",
      "confidence_basis": "1 sentence explaining the confidence level"
    }
  ],
  "seam_count": 0,
  "quiet_day": false
}

RULES:
- Maximum 3 contested narratives, 3 coverage gaps, and 2 key assumptions per deep dive candidate.
- Return fewer if fewer qualify. Empty arrays are fine — a quiet day is a quiet day.
- Set seam_count to the total number of items across all three categories.
- Set quiet_day to true if you found 0-1 total items and the source data was substantive (not just a thin day).
- All URLs must come from the source data or domain analysis links — never fabricate.
- If no relevant URL exists for a seam item, omit the links array entirely.
- Output ONLY valid JSON. No markdown, no commentary outside the JSON."""


def _collect_known_urls(raw_sources: dict, domain_analysis: dict) -> set[str]:
    """Build the set of known-good URLs from raw sources and domain artifacts."""
    known: set[str] = set()
    for item in raw_sources.get("rss", []):
        if item.get("url"):
            known.add(item["url"])
    for item in raw_sources.get("local_news", []):
        if item.get("url"):
            known.add(item["url"])
    for t in raw_sources.get("analysis_transcripts", []):
        if t.get("url"):
            known.add(t["url"])
    # URLs from domain analysis items
    for domain_result in domain_analysis.values():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []):
            for link in item.get("links", []):
                if link.get("url"):
                    known.add(link["url"])
    return known


def _build_domain_summary(domain_analysis: dict) -> str:
    """Format domain analysis artifacts for the seam detection prompt."""
    parts = []
    for domain_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        items = domain_result.get("items", [])
        if not items:
            continue
        parts.append(f"\n--- {domain_key.upper()} ANALYSIS ({len(items)} items) ---")
        for item in items:
            dive_flag = " [DEEP DIVE CANDIDATE]" if item.get("deep_dive_candidate") else ""
            parts.append(
                f"\nHeadline: {item.get('headline', '')}{dive_flag}\n"
                f"Tag: {item.get('tag', '')} | Depth: {item.get('source_depth', '')}\n"
                f"Facts: {item.get('facts', '')}\n"
                f"Analysis: {item.get('analysis', '')}"
            )
            if item.get("deep_dive_rationale"):
                parts.append(f"Dive rationale: {item['deep_dive_rationale']}")
            hooks = item.get("connection_hooks", [])
            if hooks:
                hook_strs = [
                    f"{h.get('entity', '?')}/{h.get('region', '?')}/{h.get('theme', '?')}"
                    for h in hooks[:3]
                ]
                parts.append(f"Connection hooks: {'; '.join(hook_strs)}")
            links = item.get("links", [])
            if links:
                link_strs = [f"{l.get('label', '?')}: {l.get('url', '')}" for l in links[:3]]
                parts.append(f"Links: {', '.join(link_strs)}")
        # Include market_context for econ
        if domain_key == "econ" and domain_result.get("market_context"):
            parts.append(f"\nMarket context: {domain_result['market_context']}")
    return "\n".join(parts) if parts else "(no domain analyses available)"


def _build_raw_source_summary(raw_sources: dict) -> str:
    """Format raw source data so seam detection can see what analysts had access to."""
    rss = raw_sources.get("rss", [])
    if not rss:
        return "(no raw source data)"

    # Group by category
    by_cat: dict[str, list[dict]] = {}
    for item in rss:
        cat = item.get("category", "uncategorized")
        by_cat.setdefault(cat, []).append(item)

    parts = []
    for cat, items in sorted(by_cat.items()):
        parts.append(f"\n--- {cat.upper()} ({len(items)} items) ---")
        for item in items[:12]:  # cap per category to manage prompt length
            reliability = item.get("reliability", "")
            rel_note = f" [{reliability}]" if reliability else ""
            parts.append(
                f"  {item.get('source', '?')}{rel_note}: "
                f"{item.get('title', '?')} — "
                f"{item.get('summary', '')[:200]}"
            )
            if item.get("url"):
                parts.append(f"    URL: {item['url']}")
    return "\n".join(parts)


def _build_transcript_summary(compressed_transcripts: list) -> str:
    """Format compressed transcripts for the seam detection prompt."""
    if not compressed_transcripts:
        return "(no transcripts)"
    parts = []
    for t in compressed_transcripts:
        text = t.get("compressed_transcript") or t.get("transcript", "")
        # Truncate for seam detection — it doesn't need the full transcript
        if len(text) > 500:
            text = text[:500] + "..."
        parts.append(f"{t.get('channel', '?')}: {t.get('title', '?')}\n  {text}")
    return "\n".join(parts)


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    """Detect narrative seams, coverage gaps, and key assumptions."""
    domain_analysis = context.get("domain_analysis", {})
    raw_sources = context.get("raw_sources", {})
    compressed_transcripts = context.get("compressed_transcripts", [])

    # Phase 2: use Claude Sonnet for bias diversity (different model than domain analysis)
    effective_config = model_config or config.get("llm", {}).get("seam_detection", {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "max_tokens": 5000,
        "temperature": 0.3,
    })

    # Build the comprehensive user prompt
    domain_summary = _build_domain_summary(domain_analysis)
    raw_summary = _build_raw_source_summary(raw_sources)
    transcript_summary = _build_transcript_summary(compressed_transcripts)

    user_content = f"""Review the following analytical products and source material.

=== DOMAIN ANALYSES (the product you are reviewing) ===
{domain_summary}

=== RAW SOURCE DATA (what the analysts had access to) ===
{raw_summary}

=== COMPRESSED TRANSCRIPTS (YouTube analysis channels) ===
{transcript_summary}

Perform all three detection tasks: contested narratives, coverage gaps, and key assumptions check. Output ONLY valid JSON."""

    try:
        log.info("Stage: seams — running Phase 2 seam detection...")
        result = call_llm(
            _SYSTEM_PROMPT,
            user_content,
            effective_config,
            max_retries=1,
            json_mode=True,
            stream=True,
        )

        # Validate URLs against known sources
        known_urls = _collect_known_urls(raw_sources, domain_analysis)
        result = validate_urls(result, known_urls)

        # Ensure all expected fields exist with safe defaults
        if "contested_narratives" not in result:
            result["contested_narratives"] = []
        if "coverage_gaps" not in result:
            result["coverage_gaps"] = []
        if "key_assumptions" not in result:
            result["key_assumptions"] = []

        cn = result.get("contested_narratives", [])
        cg = result.get("coverage_gaps", [])
        ka = result.get("key_assumptions", [])
        total = len(cn) + len(cg) + len(ka)
        result["seam_count"] = total
        if "quiet_day" not in result:
            result["quiet_day"] = total <= 1

        log.info(
            f"  Seam detection: {len(cn)} contested narratives, "
            f"{len(cg)} coverage gaps, {len(ka)} key assumptions"
        )
        return {"seam_data": result}

    except Exception as e:
        log.warning(f"Seam detection failed (non-fatal): {e}")
        return {"seam_data": {
            "contested_narratives": [],
            "coverage_gaps": [],
            "key_assumptions": [],
            "seam_count": 0,
            "quiet_day": True,
        }}
