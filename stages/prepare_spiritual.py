"""Stage: prepare_spiritual — small focused LLM call.

Generates a short spiritual reflection on the week's Come Follow Me reading.
Falls back to the raw CFM data (scripture text only) if the LLM call fails.

Input:  context["raw_sources"]["come_follow_me"]
Output: {"spiritual": {reading, title, key_scripture, scripture_text, reflection,
                        date_range, lesson_url, lesson_num}}
"""

import logging

from llm import call_llm
from utils.prompts import load_prompt

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("prepare_spiritual_system.md")


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    raw = context.get("raw_sources", {})
    cfm = raw.get("come_follow_me", {})

    if not cfm or not cfm.get("reading"):
        log.warning("prepare_spiritual: no Come Follow Me data available")
        return {"spiritual": {}}

    # Build reflection prompt
    user_content = (
        f"Week: {cfm.get('date_range', 'This week')}\n"
        f"Reading: {cfm.get('reading', '')}\n"
        f"Title: {cfm.get('title', '')}\n"
        f"Key scripture ({cfm.get('key_scripture', '')}): "
        f"{cfm.get('scripture_text', '')}\n\n"
        f"Write the spiritual thought."
    )

    reflection = ""
    if model_config:
        try:
            reflection = call_llm(
                _SYSTEM_PROMPT,
                user_content,
                model_config,
                max_retries=1,
                json_mode=False,
                stream=True,
            )
            log.info("prepare_spiritual: reflection generated")
        except Exception as e:
            log.warning(f"prepare_spiritual: LLM call failed, using scripture text only: {e}")
    else:
        log.info("prepare_spiritual: no model config, using scripture text only")

    return {
        "spiritual": {
            **cfm,
            "reflection": reflection.strip() if reflection else cfm.get("scripture_text", ""),
        }
    }
