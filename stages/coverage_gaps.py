"""Stage: coverage_gaps — Self-audit for source blind-spot detection.

Diagnostic stage that identifies important topics with zero or near-zero
coverage in today's source pull. Output is diagnostic-only: it appears in
artifacts and dry-run output but not in the normal email.

Position in pipeline: after cross_domain, before assemble.

Inputs:  domain_analysis (dict), cross_domain_plan (dict)
Outputs: coverage_gaps (dict)

Per-run artifact: output/artifacts/YYYY-MM-DD/coverage_gaps.json
History: output/coverage_gaps_history.jsonl (append-only)

Non-critical: returns empty results on failure so the pipeline can continue.
"""

import json
import logging
from pathlib import Path

from llm import call_llm
from utils.prompts import load_prompt
from utils.time import artifact_date

log = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).parent.parent / "output"
_HISTORY_FILE = _OUTPUT_DIR / "coverage_gaps_history.jsonl"


def _build_domain_summary(domain_analysis: dict) -> str:
    """Summarize domain analyses for the coverage gap prompt."""
    parts = []
    for domain_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        items = domain_result.get("items", [])
        if not items:
            parts.append(f"\n--- {domain_key.upper()}: (no items) ---")
            continue
        parts.append(f"\n--- {domain_key.upper()} ({len(items)} items) ---")
        for item in items:
            parts.append(
                f"  - [{item.get('tag', '?')}] {item.get('headline', '?')}"
            )
    return "\n".join(parts) if parts else "(no domain analyses available)"


def _build_plan_summary(cross_domain_plan: dict) -> str:
    """Summarize the editorial plan for context."""
    if not cross_domain_plan:
        return "(no editorial plan available)"
    parts = []
    for dive in cross_domain_plan.get("deep_dives", []):
        parts.append(f"  Deep dive: {dive.get('topic', '?')}")
    for wr in cross_domain_plan.get("worth_reading", []):
        parts.append(f"  Worth reading: {wr.get('topic', '?')}")
    return "\n".join(parts) if parts else "(plan has no selections)"


def _load_recent_history(max_entries: int = 7) -> list[dict]:
    """Load recent coverage gap history entries for recurring pattern detection."""
    if not _HISTORY_FILE.exists():
        return []
    entries = []
    try:
        with open(_HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        log.warning(f"Failed to read coverage gap history: {e}")
        return []
    return entries[-max_entries:]


def _append_history(result: dict) -> None:
    """Append today's coverage gap result to history."""
    _OUTPUT_DIR.mkdir(exist_ok=True)
    try:
        with open(_HISTORY_FILE, "a") as f:
            f.write(json.dumps(result, default=str) + "\n")
    except Exception as e:
        log.warning(f"Failed to append coverage gap history: {e}")


def _build_recurring_context(history: list[dict]) -> str:
    """Build context about recurring gaps for the prompt."""
    if not history:
        return "No prior coverage gap reports are available."
    # Extract recent gap topics for recurrence detection
    recent_topics = []
    for entry in history:
        date = entry.get("date", "?")
        for gap in entry.get("gaps", []):
            recent_topics.append(f"  - [{date}] {gap.get('topic', '?')}: {gap.get('description', '?')}")
    if not recent_topics:
        return "Prior coverage gap reports found no significant gaps."
    return (
        "Recent coverage gap history (check for recurring patterns):\n"
        + "\n".join(recent_topics[-15:])  # cap at 15 most recent
    )


def _empty_result(date: str) -> dict:
    return {
        "schema_version": 1,
        "date": date,
        "gaps": [],
        "recurring_patterns": [],
    }


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    """Run coverage gap detection and return diagnostic output."""
    date = artifact_date()
    domain_analysis = context.get("domain_analysis", {})
    cross_domain_plan = context.get("cross_domain_plan", {})

    if not domain_analysis:
        log.warning("coverage_gaps: no domain_analysis available, skipping")
        return {"coverage_gaps": _empty_result(date)}

    if not model_config:
        model_config = config.get("llm", {})

    # Build prompt inputs
    domain_summary = _build_domain_summary(domain_analysis)
    plan_summary = _build_plan_summary(cross_domain_plan)
    history = _load_recent_history()
    recurring_context = _build_recurring_context(history)

    system_prompt = load_prompt(
        "coverage_gaps.md",
        {"date": date, "recurring_context": recurring_context},
    )

    user_content = (
        f"Today's date: {date}\n\n"
        f"DOMAIN ANALYSES:\n{domain_summary}\n\n"
        f"EDITORIAL PLAN:\n{plan_summary}\n\n"
        "Identify significant coverage gaps."
    )

    try:
        result = call_llm(
            system_prompt,
            user_content,
            model_config,
            max_retries=1,
            json_mode=True,
        )
    except Exception as e:
        log.error(f"coverage_gaps: LLM call failed: {e}")
        return {"coverage_gaps": _empty_result(date)}

    # Normalize result
    if not isinstance(result, dict):
        result = _empty_result(date)
    result.setdefault("schema_version", 1)
    result.setdefault("date", date)
    result.setdefault("gaps", [])
    result.setdefault("recurring_patterns", [])

    # Cap gaps at 5
    result["gaps"] = result["gaps"][:5]

    # Append to history
    _append_history(result)

    gap_count = len(result["gaps"])
    pattern_count = len(result["recurring_patterns"])
    log.info(
        f"coverage_gaps: {gap_count} gaps identified, "
        f"{pattern_count} recurring patterns"
    )

    return {"coverage_gaps": result}
