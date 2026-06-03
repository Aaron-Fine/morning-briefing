"""Single source of truth for digest tag vocabulary and labels.

`tag` is produced (and validated) by the analysis desks; `tag_label` is always
derived from `tag` here rather than emitted by any LLM. `desk_tag_set` exposes the
allowed tags per desk, derived from analyze_domain's _DOMAIN_CONFIGS so the
vocabulary has exactly one definition.
"""

from __future__ import annotations

TAG_LABELS: dict[str, str] = {
    "war": "Conflict",
    "domestic": "Politics",
    "econ": "Economy",
    "ai": "AI",
    "tech": "Technology",
    "defense": "Defense",
    "space": "Space",
    "cyber": "Cyber",
    "local": "Local",
    "science": "Science",
    "energy": "Energy",
    "biotech": "Biotech",
}

VALID_TAGS = frozenset(TAG_LABELS)


def label_for_tag(tag: str) -> str:
    """Human-readable label for a tag; safe titlecase fallback for unknowns."""
    return TAG_LABELS.get(tag, str(tag).replace("-", " ").title().replace(" ", "-"))


def desk_tag_set(desk_key: str) -> set[str]:
    """Allowed tags for a desk, parsed from analyze_domain's _DOMAIN_CONFIGS 'tags'."""
    from stages.analyze_domain import _DOMAIN_CONFIGS

    cfg = _DOMAIN_CONFIGS.get(desk_key)
    if not cfg:
        return set()
    return {t.strip() for t in str(cfg.get("tags", "")).split("|") if t.strip()}
