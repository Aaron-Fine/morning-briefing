"""Stage: prepare_local — deterministic, no LLM.

Selects the top local news items from raw_sources, capped at
digest.local.max_items. Items are already sorted by recency from collect stage.
Filters out syndicated press releases that are not genuinely local to Cache Valley.

Input:  context["raw_sources"]["local_news"]
Output: {"local_items": [...]}
"""

import logging

log = logging.getLogger(__name__)

# Wire service markers that indicate a syndicated national press release
_WIRE_MARKERS = [
    "PRNewswire",
    "/ PRNewswire/",
    "Business Wire",
    "GlobeNewswire",
    "PR Newswire",
]


def _is_local_news(item: dict) -> bool:
    """Return True if item appears to be genuine Cache Valley local news.

    Rejects:
    - Items under a /press_releases/ URL path (outlet-hosted wire syndication)
    - Items whose summary body contains a wire service byline
    """
    url = item.get("url", "") or ""
    summary = item.get("summary", "") or ""
    if "/press_releases/" in url:
        return False
    if any(marker in summary for marker in _WIRE_MARKERS):
        return False
    return True


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    raw = context.get("raw_sources", {})
    local_news = raw.get("local_news", [])
    max_items = config.get("digest", {}).get("local", {}).get("max_items", 4)

    local_only = [item for item in local_news if _is_local_news(item)]
    selected = local_only[:max_items]

    log.info(
        f"prepare_local: {len(local_news)} raw items → {len(local_only)} local "
        f"(filtered {len(local_news) - len(local_only)} press releases) → {len(selected)} selected "
        f"(max_items={max_items})"
    )
    return {"local_items": selected}
