"""Stage: seams — Detect narrative disagreements and coverage gaps.

Inputs:  synthesis_output (dict), raw_sources (dict)
Outputs: seam_data (dict)

Non-critical: returns empty results on failure so the pipeline can continue.
"""

import json
import logging

from llm import call_llm
from validate import validate_urls

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a media analysis assistant. You will receive a synthesized news digest
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


def run(inputs: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    """Detect narrative seams and return seam_data artifact."""
    synthesis_output = inputs.get("synthesis_output", {})
    raw_sources = inputs.get("raw_sources", {})

    effective_config = model_config or config.get("llm", {}).get("seam_detection", {
        "provider": "fireworks",
        "model": "accounts/fireworks/models/kimi-k2p5",
        "max_tokens": 5000,
        "temperature": 0.3,
    })

    # Build category coverage map
    rss = raw_sources.get("rss", [])
    category_coverage: dict[str, list[str]] = {}
    for item in rss:
        cat = item.get("category", "uncategorized")
        category_coverage.setdefault(cat, []).append(item.get("title", ""))
    for t in raw_sources.get("analysis_transcripts", []):
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
        log.info("Stage: seams — running seam detection...")
        result = call_llm(
            _SYSTEM_PROMPT,
            user_content,
            effective_config,
            max_retries=1,
            json_mode=True,
            stream=False,
        )

        # Collect known URLs from synthesis output for URL validation
        known_urls: set[str] = set()
        for item in synthesis_output.get("at_a_glance", []):
            for link in item.get("links", []):
                if link.get("url"):
                    known_urls.add(link["url"])
        for dive in synthesis_output.get("deep_dives", []):
            for fr in dive.get("further_reading", []):
                if fr.get("url"):
                    known_urls.add(fr["url"])

        result = validate_urls(result, known_urls)

        cn = result.get("contested_narratives", [])
        cg = result.get("coverage_gaps", [])
        log.info(f"  Seam detection: {len(cn)} contested narratives, {len(cg)} coverage gaps")
        return {"seam_data": result}

    except Exception as e:
        log.warning(f"Seam detection failed (non-fatal): {e}")
        return {"seam_data": {"contested_narratives": [], "coverage_gaps": []}}
