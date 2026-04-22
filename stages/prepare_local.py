"""Stage: prepare_local — deterministic, no LLM.

Selects the top Cache Valley and Utah/Western regional news items from
raw_sources. Items are already sorted by recency from collect stage.
Filters out syndicated press releases that are not genuinely local to Cache Valley.

Input:  context["raw_sources"]["local_news"], context["raw_sources"]["rss"]
Output: {"local_items": [...], "regional_items": [...]}
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
CONSUMED_RSS_CATEGORIES = {"regional-west"}


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


def _has_useful_summary(item: dict) -> bool:
    summary = (item.get("summary") or item.get("_rss_body") or "").strip()
    return len(summary) >= 40


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    raw = context.get("raw_sources", {})
    local_news = raw.get("local_news", [])
    regional_news = [
        item for item in raw.get("rss", []) if item.get("category") == "regional-west"
    ]
    local_cfg = config.get("digest", {}).get("local", {})
    max_items = local_cfg.get("max_items", 4)
    max_regional_items = local_cfg.get("max_regional_items", max_items)

    local_only = [item for item in local_news if _is_local_news(item)]
    useful = [item for item in local_only if _has_useful_summary(item)]
    thin = [item for item in local_only if not _has_useful_summary(item)]
    selected = (useful + thin)[:max_items]

    regional_useful = [item for item in regional_news if _has_useful_summary(item)]
    regional_thin = [item for item in regional_news if not _has_useful_summary(item)]
    selected_regional = (regional_useful + regional_thin)[:max_regional_items]

    log.info(
        f"prepare_local: {len(local_news)} raw items → {len(local_only)} local "
        f"(filtered {len(local_news) - len(local_only)} press releases; "
        f"{len(thin)} empty/thin summaries) → {len(selected)} selected "
        f"(max_items={max_items}); {len(regional_news)} regional-west RSS items → "
        f"{len(selected_regional)} selected (max_regional_items={max_regional_items})"
    )
    return {"local_items": selected, "regional_items": selected_regional}
