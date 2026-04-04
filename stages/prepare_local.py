"""Stage: prepare_local — deterministic, no LLM.

Selects the top local news items from raw_sources, capped at
digest.local.max_items. Items are already sorted by recency from collect stage.

Input:  context["raw_sources"]["local_news"]
Output: {"local_items": [...]}
"""

import logging

log = logging.getLogger(__name__)


def run(context: dict, config: dict, model_config, **kwargs) -> dict:
    raw = context.get("raw_sources", {})
    local_news = raw.get("local_news", [])
    max_items = config.get("digest", {}).get("local", {}).get("max_items", 4)
    selected = local_news[:max_items]
    log.info(
        f"prepare_local: {len(local_news)} items → {len(selected)} selected "
        f"(max_items={max_items})"
    )
    return {"local_items": selected}
