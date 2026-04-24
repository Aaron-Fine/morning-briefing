"""Shared schema for daily spiritual units.

Both `prepare_spiritual_weekly` (producer) and `prepare_spiritual` (consumer)
need to normalize raw unit dicts into a common shape. The valid kinds and the
normalization logic live here so the two stages cannot drift apart.
"""

VALID_DAILY_UNIT_KINDS = frozenset(
    {
        "narrative_unit",
        "key_scripture",
        "misuse_correction",
        "scholarly_insight",
        "language_context",
        "faithful_application",
    }
)


def _from_legacy_foci(foci: list) -> list[dict]:
    return [
        {
            "id": focus.get("id", ""),
            "kind": "narrative_unit",
            "title": focus.get("text_ref", ""),
            "anchor_ref": focus.get("text_ref", ""),
            "source_refs": [focus.get("text_ref", "")],
            "core_claim": "",
            "supporting_excerpt": focus.get("guide_excerpt", ""),
            "enhancement": "",
            "application": "",
            "prompt_hint": "",
        }
        for focus in (foci or [])
        if isinstance(focus, dict)
    ]


def normalize_daily_units(source: dict) -> list[dict]:
    """Coerce a dict containing `daily_units` (or legacy `daily_foci`) into a
    list of fully-populated unit dicts. Guarantees unique IDs and valid kinds.
    """
    raw_units = source.get("daily_units", []) or []
    if not raw_units:
        raw_units = _from_legacy_foci(source.get("daily_foci", []))

    normalized: list[dict] = []
    seen_ids: set[str] = set()
    for idx, unit in enumerate(raw_units, start=1):
        if not isinstance(unit, dict):
            continue

        unit_id = str(unit.get("id") or f"focus-{idx}").strip()
        if not unit_id or unit_id in seen_ids:
            unit_id = f"focus-{idx}"
        seen_ids.add(unit_id)

        kind = str(unit.get("kind", "")).strip().lower() or "narrative_unit"
        if kind not in VALID_DAILY_UNIT_KINDS:
            kind = "narrative_unit"

        source_refs = [
            str(ref).strip()
            for ref in (unit.get("source_refs", []) or [])
            if str(ref).strip()
        ]
        anchor_ref = str(unit.get("anchor_ref", "")).strip()
        if anchor_ref and anchor_ref not in source_refs:
            source_refs.insert(0, anchor_ref)
        if not anchor_ref and source_refs:
            anchor_ref = source_refs[0]

        normalized.append(
            {
                "id": unit_id,
                "kind": kind,
                "title": str(unit.get("title", "")).strip(),
                "anchor_ref": anchor_ref,
                "source_refs": source_refs,
                "core_claim": str(unit.get("core_claim", "")).strip(),
                "supporting_excerpt": str(
                    unit.get("supporting_excerpt") or unit.get("guide_excerpt", "")
                ).strip(),
                "enhancement": str(unit.get("enhancement", "")).strip(),
                "application": str(unit.get("application", "")).strip(),
                "prompt_hint": str(unit.get("prompt_hint", "")).strip(),
            }
        )
    return normalized
