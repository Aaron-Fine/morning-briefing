# PR-A: Appendix A Override Removal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the deterministic-override sprawl in the cross_domain/seams path so the LLM does selection + judgment only, and Python does the joins, derivations, and caps — eliminating the "LLM emits it, code rewrites it" pattern for `tag`, `tag_label`, verbatim `facts`/`analysis`, `domains_bridged`, the "exactly N" quotas, the hedged-seam regex, and the duplicate prompt-side caps.

**Architecture:** The cross_domain execute LLM stops emitting derivable fields. For `at_a_glance` it emits only `{item_id, cross_domain_note}` (array order = ranking); a new `_join_at_a_glance` joins `headline`/`facts`/`analysis`/`links`/`connection_hooks`/`source_depth`/`tag` from the desk item identified by `item_id`, and `tag_label` derives from `tag`. Because `item_id` is `{domain_key}-{hash}` and every desk item already carries a desk-validated `tag`, deriving `tag` from desk-of-origin (#2) and the verbatim-copy elimination (#3) collapse into that one join. `domains_bridged` (#12) derives from each deep dive's `further_reading` URLs mapped back to desks. The hedged-seam regex filter (#15 sweep) is deleted in favor of the prompt's existing named-perspective voice discipline.

**Tech Stack:** Python 3.13, pytest, ruff. No new dependencies.

**Scope (locked with stakeholder):** Core named set (#1 `tag_label`, #2 `tag`, #3 verbatim copy, #5 exactly-N, prompt-side duplicate caps, regex sweep) **plus** #4 (seam-links doc cleanup) and #12 (`domains_bridged` derive). **Deferred and explicitly out of scope:** #14 `source_depth` desk-schema drop → PR-E (don't touch `_recompute_source_depth` twice); #8 per-outlet cap consolidation → PR-C; #11 `_ensure_primary_glance_coverage` → PR-D; #13 dedup safety net → PR-E; #6/#7 seam evidence-gate graph queries → PR-D/PR-I; #9 `coverage_gaps` cap → moot (stage being deleted wholesale); #15 LOW `compress.py` target-words → deferred (not part of the named sweep).

**Reference:** Master checklist is `docs/exploration/lemongraph-seams-assessment.md` Appendix A (15 findings). Epic: `docs/superpowers/plans/2026-05-24-Graph-Epic.md`. The epic's first success criterion requires every Appendix A finding be either removed or moved to the "not doing on purpose" bucket with a one-line reason (Task 9).

---

## Environment & conventions

- **Isolation:** Work in a git worktree created via `superpowers:using-git-worktrees` at execution start (branch `pr-A-override-removal`). Per the project Docker workflow, build the `morning-digest-dev` image and mount the worktree over `/app`.
- **All test/ruff commands run inside the container.** Wherever a step says `pytest …` or `ruff …`, run it as:
  ```bash
  docker run --rm -v "$PWD":/app morning-digest-dev pytest …
  docker run --rm -v "$PWD":/app morning-digest-dev ruff check .
  ```
  Never run host conda/pytest.
- **Commit cadence:** one commit per task (conventional commits), pushing every few tasks. PR opened at the end.
- **PR-B baseline caveat:** PR-A changes prompt text. The PR-B rendered-prompt baseline (`output/prompt_baseline/`) captured at the end of PR-0 is therefore intentionally invalidated by this PR and must be re-captured (Task 10) so PR-B diffs against post-PR-A prompts.

---

## File map

| File | Change |
|------|--------|
| `stages/assemble.py` | Delete `_HEDGED_SEAM_RE` + its use (#15 sweep). Replace local `_TAG_LABELS` with shared constant import (#1). |
| `prompts/seam_annotations.md` | Drop "Return at most 6 per_item annotations" prompt cap (#10). Add note that `links` are pipeline-supplied, not LLM (#4). |
| `prompts/cross_domain_plan.md` | "Return exactly N" → "Return up to N" for connections/deep_dives/worth_reading (#5). |
| `prompts/cross_domain_execute.md` | Shrink `at_a_glance` schema to `{item_id, cross_domain_note}`; drop `tag`/`tag_label`/verbatim-copy instruction (#1/#2/#3). Drop `domains_bridged` from deep-dive schema (#12). "exactly N" → "up to N" (#5). |
| `cross_domain/parse.py` | New `_TAG_LABELS` → moved to `morning_digest/tags.py` (shared). New `_join_at_a_glance` + `_derive_domains_bridged`. Delete `_normalize_tag`, `_TAG_KEYWORDS`, `_VALID_TAGS` if unused after. Rewire `_validated_output`. |
| `morning_digest/tags.py` | **New** — single source of truth for `TAG_LABELS` + `desk_tag_set` helper; imported by parse/assemble/validate. |
| `morning_digest/validate.py` | Use shared `TAG_LABELS`; tag fallback becomes defensive-only (documented). |
| `cross_domain/stage.py` | Wire `domain_analysis` into the join (already available). |
| `stages/seams.py` | Comment clarifying `_links_by_item_id` is authoritative (#4). |
| `docs/exploration/lemongraph-seams-assessment.md` | Mark each Appendix A finding's disposition (Task 9). |
| `docs/prompt-baseline-README.md` + `output/prompt_baseline/` | Re-capture post-PR-A baseline (Task 10). |
| `TODO.md` | Check off PR-A. |

---

## Task 1: Regex sweep — delete `_HEDGED_SEAM_RE`

**Why:** Appendix A #15 sweep. The render-time hedged-seam filter in `assemble.py` rewrites/drops LLM output that `prompts/seam_annotations.md` already forbids (lines 59–64 "named perspective, not hedged attribution" + negative examples). Prompt discipline is the source of truth; the regex is the override.

**Files:**
- Modify: `stages/assemble.py` (delete `_HEDGED_SEAM_RE` def ~`:52-56` and its use ~`:161`)
- Test: `tests/test_assemble.py`

- [ ] **Step 1: Write the failing test** — a hedged `one_line` annotation now survives selection (no longer silently dropped at render).

```python
# tests/test_assemble.py
def test_hedged_seam_annotation_is_not_dropped_at_render():
    """PR-A #15 sweep: assemble no longer filters hedged one_line text;
    the seam prompt enforces named-perspective voice instead."""
    from stages.assemble import _select_inline_seam_annotations

    annotations = [
        {
            "item_id": "ai_tech-abc",
            "one_line": "Some analysts argue the benchmark gain is overstated.",
            "seam_type": "credible_dissent",
            "confidence": "high",
        }
    ]
    at_a_glance = [{"item_id": "ai_tech-abc"}]
    selected = _select_inline_seam_annotations(at_a_glance, annotations)
    assert selected.get("ai_tech-abc", {}).get("one_line", "").startswith("Some analysts")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_assemble.py::test_hedged_seam_annotation_is_not_dropped_at_render -v`
Expected: FAIL — the annotation is filtered out by `_HEDGED_SEAM_RE`, so `selected` is empty. (If `_select_inline_seam_annotations` has a different signature, adapt the call to the real one read from `assemble.py:149-184` — keep the assertion that a hedged line survives.)

- [ ] **Step 3: Delete the regex and its use**

In `stages/assemble.py` delete the block:
```python
_HEDGED_SEAM_RE = re.compile(
    r"^\s*(some analysts argue|critics say|observers (?:say|believe)|"
    r"some experts (?:say|argue)|there are concerns)\b",
    re.IGNORECASE,
)
```
and remove the guard (around line 161):
```python
        if _HEDGED_SEAM_RE.match(one_line):
            continue
```
If `re` is now unused in the file, remove the `import re`. (Verify with `ruff check stages/assemble.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_assemble.py::test_hedged_seam_annotation_is_not_dropped_at_render -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stages/assemble.py tests/test_assemble.py
git commit -m "refactor(seams): drop _HEDGED_SEAM_RE render filter; rely on prompt voice discipline (Appendix A #15)"
```

---

## Task 2: Relax "exactly N" → "up to N" quotas (#5)

**Why:** Appendix A #5. `_normalize_cross_domain_plan` already truncates each list to the configured count; the prompt's "exactly N" wording overconstrains low-evidence days where fewer items is the honest output. Code stays the cap; prompt becomes a ceiling.

**Files:**
- Modify: `prompts/cross_domain_plan.md` (lines 16, 20, 28)
- Modify: `prompts/cross_domain_execute.md` (lines 28, 38)
- Test: `tests/test_cross_domain.py` (assert truncation still caps; underproduction passes through)

- [ ] **Step 1: Write the failing test** — underproduction is accepted; overproduction is capped.

```python
# tests/test_cross_domain.py
def test_plan_accepts_underproduction_and_caps_overproduction():
    from cross_domain.parse import _normalize_cross_domain_plan

    # Underproduction: 1 connection where 3 requested — accepted as-is.
    under = _normalize_cross_domain_plan(
        {"cross_domain_connections": [{"description": "a"}]},
        deep_dive_count=2, worth_reading_count=3, connection_count=3,
    )
    assert len(under["cross_domain_connections"]) == 1

    # Overproduction: 5 deep_dives where 2 requested — capped to 2.
    over = _normalize_cross_domain_plan(
        {"deep_dives": [{"topic": str(i)} for i in range(5)]},
        deep_dive_count=2, worth_reading_count=3, connection_count=3,
    )
    assert len(over["deep_dives"]) == 2
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/test_cross_domain.py::test_plan_accepts_underproduction_and_caps_overproduction -v`
Expected: PASS already (the truncation code is unchanged). This test pins the behavior the prompt change relies on — if it already passes, that is correct; proceed to the prompt edit. (TDD note: this is a characterization test guarding that the prompt relaxation does not require code changes.)

- [ ] **Step 3: Edit the prompts**

In `prompts/cross_domain_plan.md`:
- Line 16: `Return exactly ${connection_count} \`cross_domain_connections\`.` → `Return up to ${connection_count} \`cross_domain_connections\` — fewer is correct when the evidence does not support that many.`
- Line 20: `Return exactly ${deep_dive_count} \`deep_dives\`.` → `Return up to ${deep_dive_count} \`deep_dives\`.`
- Line 28: `Return exactly ${worth_reading_count} \`worth_reading\` entries.` → `Return up to ${worth_reading_count} \`worth_reading\` entries.`

In `prompts/cross_domain_execute.md`:
- Line 28: `Write exactly ${deep_dive_count} deep dives unless the available evidence makes one of the planned topics unsupported.` → `Write up to ${deep_dive_count} deep dives; write fewer when the available evidence makes a planned topic unsupported.`
- Line 38: `Return exactly ${worth_reading_count} entries unless the plan includes an unsupported topic.` → `Return up to ${worth_reading_count} entries; fewer is fine when the plan includes an unsupported topic.`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cross_domain.py::test_plan_accepts_underproduction_and_caps_overproduction -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add prompts/cross_domain_plan.md prompts/cross_domain_execute.md tests/test_cross_domain.py
git commit -m "refactor(cross_domain): relax 'exactly N' quotas to 'up to N'; code cap is the source of truth (Appendix A #5)"
```

---

## Task 3: Drop prompt-side seam per_item cap (#10)

**Why:** Appendix A #10. `seam_annotations.md:69` says "Return at most 6 per_item annotations," but `seams.py:471-479` truncates by confidence and `assemble.py:149-184` collapses to one annotation per item — the LLM is budgeting against two later overrides. Drop the prompt number; the code is the real constraint.

**Files:**
- Modify: `prompts/seam_annotations.md` (line 69)
- Test: none new (behavior is enforced in `seams.py`/`assemble.py`, already covered). Verify existing seam tests still pass.

- [ ] **Step 1: Edit the prompt**

In `prompts/seam_annotations.md`, line 69:
`Return at most 6 \`per_item\` annotations. Choose the strongest evidence, not the most interesting speculation.`
→
`Return only annotations that clear the evidence gate and novelty filter — quality over quantity. The pipeline keeps the highest-confidence annotations per item, so do not pad.`

- [ ] **Step 2: Run the seam tests to confirm no regression**

Run: `pytest tests/ -k seam -v`
Expected: PASS (the code-side truncation/collapse is unchanged).

- [ ] **Step 3: Commit**

```bash
git add prompts/seam_annotations.md
git commit -m "refactor(seams): drop prompt-side 'at most 6' cap; code truncation + per-item collapse are the constraint (Appendix A #10)"
```

---

## Task 4: Single source of truth for `TAG_LABELS`; derive in code (#1)

**Why:** Appendix A #1. `_TAG_LABELS` is hardcoded three times (`cross_domain/parse.py:27`, `stages/assemble.py:37`, and `VALID_TAG_LABELS` in `validate.py`). `tag_label` is purely derivable from `tag`. Consolidate to one map and derive at point of use; the execute prompt stops asking for `tag_label` (handled fully in Task 5's schema edit, but the shared map lands here first because Task 5 depends on it).

**Files:**
- Create: `morning_digest/tags.py`
- Modify: `cross_domain/parse.py` (import shared `TAG_LABELS`, drop local dup)
- Modify: `stages/assemble.py` (import shared `TAG_LABELS`, drop local `_TAG_LABELS`)
- Modify: `morning_digest/validate.py` (use shared `TAG_LABELS`)
- Test: `tests/test_tags.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tags.py
def test_tag_labels_single_source_and_desk_tag_sets():
    from morning_digest.tags import TAG_LABELS, desk_tag_set, label_for_tag

    assert TAG_LABELS["war"] == "Conflict"
    assert label_for_tag("ai") == "AI"
    assert label_for_tag("not-a-tag") == "Not-A-Tag"  # safe titlecase fallback
    # Desk → allowed tag set, derived from analyze_domain _DOMAIN_CONFIGS.
    assert desk_tag_set("ai_tech") == {"ai", "tech", "cyber"}
    assert desk_tag_set("econ") == {"econ"}
    assert desk_tag_set("unknown_desk") == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tags.py -v`
Expected: FAIL — `morning_digest.tags` does not exist.

- [ ] **Step 3: Create the shared module**

```python
# morning_digest/tags.py
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
```

Note on the fallback: `label_for_tag("not-a-tag")` → `"Not-A-Tag"` (title-cases words, rejoins on hyphen). Adjust the test if a simpler `.capitalize()` fallback is preferred — keep the two consistent.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tags.py -v`
Expected: PASS

- [ ] **Step 5: Rewire the three call sites to the shared map**

In `cross_domain/parse.py`: delete the local `_TAG_LABELS = {…}` (lines 27–40) and add `from morning_digest.tags import TAG_LABELS as _TAG_LABELS`. (Keep the `_TAG_LABELS` alias so existing references in `_fallback_glance_item` keep working.)

In `stages/assemble.py`: delete the local `_TAG_LABELS = {…}` (line 37+) and `from morning_digest.tags import label_for_tag`. Replace `item.get("tag_label") or _TAG_LABELS.get(tag, tag.capitalize())` (line 76) with `item.get("tag_label") or label_for_tag(tag)`.

In `morning_digest/validate.py`: replace `VALID_TAG_LABELS.get(tag, tag.capitalize())` (line 242) usage with the shared map — `from morning_digest.tags import label_for_tag, VALID_TAGS` and set `entry["tag_label"] = item.get("tag_label") or label_for_tag(tag)`; replace the local `VALID_TAGS`/`VALID_TAG_LABELS` definitions with the import (grep for their definitions and remove).

- [ ] **Step 6: Run the affected suites**

Run: `pytest tests/test_tags.py tests/test_assemble.py tests/test_validate.py tests/test_cross_domain.py -v`
Expected: PASS. Fix any import drift surfaced by `ruff check .`.

- [ ] **Step 7: Commit**

```bash
git add morning_digest/tags.py cross_domain/parse.py stages/assemble.py morning_digest/validate.py tests/test_tags.py
git commit -m "refactor(tags): single TAG_LABELS source of truth; derive tag_label in code (Appendix A #1)"
```

---

## Task 5: Selection-join for `at_a_glance` — derive `tag` from desk, drop verbatim copy (#2, #3)

**Why:** Appendix A #2 + #3 — the architectural core. The execute LLM is told to copy `item_id`/`facts`/`analysis` verbatim and emit a `tag` the code then remaps via the 100-entry `_TAG_KEYWORDS` table. Both vanish if the LLM emits only a **selection** (`item_id` + `cross_domain_note`, array order = ranking) and code joins the rest from the desk item identified by `item_id` (`{domain_key}-{hash}`). The desk item already carries a desk-validated `tag`, so `tag` derives from desk-of-origin for free; `tag_label` derives via Task 4. Typo'd item_ids no longer carry mangled prose — they simply fail the join and are dropped (logged), eliminating the "LLM mangled the verbatim copy" diagnostic class.

**Files:**
- Modify: `prompts/cross_domain_execute.md` (at_a_glance schema + execution rules)
- Modify: `cross_domain/parse.py` (new `_join_at_a_glance`; rewire `_validated_output`; delete `_normalize_tag`/`_TAG_KEYWORDS`/`_VALID_TAGS` if unused; update `_fallback_glance_item`)
- Modify: `morning_digest/contracts.py` (at_a_glance normalizer tolerates the minimal selection shape)
- Test: `tests/test_cross_domain.py`, `tests/test_cross_domain_two_turn.py`

- [ ] **Step 1: Write the failing test** — the join builds full items from a minimal selection and derives `tag` from the desk.

```python
# tests/test_cross_domain.py
def test_join_at_a_glance_builds_full_items_from_selection():
    from cross_domain.parse import _join_at_a_glance

    domain_analysis = {
        "ai_tech": {
            "items": [
                {
                    "item_id": "ai_tech-deadbeef",
                    "tag": "ai",
                    "headline": "Frontier model ships",
                    "facts": "Lab X released model Y.",
                    "analysis": "Raises the deployment bar.",
                    "source_depth": "corroborated",
                    "links": [{"url": "https://ex.com/a", "label": "Ex"}],
                    "connection_hooks": [{"entity": "Lab X"}],
                },
            ]
        }
    }
    # LLM emitted only selection + note (array order = ranking).
    llm_result = {
        "at_a_glance": [
            {"item_id": "ai_tech-deadbeef", "cross_domain_note": "Ties to the chip-export thread."},
            {"item_id": "ai_tech-MISSING", "cross_domain_note": "typo — should drop"},
        ]
    }
    joined = _join_at_a_glance(llm_result["at_a_glance"], domain_analysis)
    assert len(joined) == 1                       # typo'd id dropped
    item = joined[0]
    assert item["facts"] == "Lab X released model Y."        # joined from desk
    assert item["analysis"] == "Raises the deployment bar."  # joined from desk
    assert item["tag"] == "ai"                    # derived from desk item (#2)
    assert item["tag_label"] == "AI"              # derived from tag (#1)
    assert item["cross_domain_note"] == "Ties to the chip-export thread."  # LLM contribution kept
    assert item["headline"] == "Frontier model ships"
    assert item["links"] == [{"url": "https://ex.com/a", "label": "Ex"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cross_domain.py::test_join_at_a_glance_builds_full_items_from_selection -v`
Expected: FAIL — `_join_at_a_glance` does not exist.

- [ ] **Step 3: Implement the join in `cross_domain/parse.py`**

Add near the other helpers:
```python
from morning_digest.tags import TAG_LABELS, label_for_tag  # at top with other imports


def _index_domain_items(domain_analysis: dict) -> dict[str, dict]:
    """Map item_id -> the desk item dict, across all desks."""
    index: dict[str, dict] = {}
    for domain_result in domain_analysis.values():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []) or []:
            if isinstance(item, dict) and item.get("item_id"):
                index[item["item_id"]] = item
    return index


# Fields the LLM may legitimately contribute per selected item; everything else
# is joined from the desk item by item_id.
_GLANCE_LLM_FIELDS = ("cross_domain_note",)


def _join_at_a_glance(selection: list[dict], domain_analysis: dict) -> list[dict]:
    """Build full at_a_glance items from an LLM selection of item_ids.

    The execute LLM emits only {item_id, cross_domain_note}; array order is the
    ranking. Code joins headline/facts/analysis/links/connection_hooks/source_depth
    from the desk item, derives `tag` from the desk item (desk-of-origin) and
    `tag_label` from `tag`. Selections whose item_id is unknown are dropped.
    """
    index = _index_domain_items(domain_analysis)
    joined: list[dict] = []
    dropped = 0
    for sel in selection:
        if not isinstance(sel, dict):
            continue
        item_id = str(sel.get("item_id", "")).strip()
        source = index.get(item_id)
        if source is None:
            dropped += 1
            continue
        tag = str(source.get("tag", "")).strip()
        entry = {
            "item_id": item_id,
            "tag": tag,
            "tag_label": label_for_tag(tag),
            "headline": str(source.get("headline", "")).strip(),
            "facts": str(source.get("facts", "")),
            "analysis": str(source.get("analysis", "")),
            "source_depth": source.get("source_depth", "single-source"),
            "cross_domain_note": sel.get("cross_domain_note") or None,
            "links": list(source.get("links", []) or []),
            "connection_hooks": list(source.get("connection_hooks", []) or []),
        }
        joined.append(entry)
    if dropped:
        log.info("  cross_domain: dropped %s at_a_glance selection(s) with unknown item_id", dropped)
    return joined
```

- [ ] **Step 4: Run the unit test to verify the join passes**

Run: `pytest tests/test_cross_domain.py::test_join_at_a_glance_builds_full_items_from_selection -v`
Expected: PASS

- [ ] **Step 5: Wire the join into `_validated_output` and delete the tag override**

In `cross_domain/parse.py` `_validated_output`, replace the tag/tag_label override loop (the block that calls `_normalize_tag` and sets `tag_label`, lines ~617–626) with the join, run **before** the link-pruning/cap logic:
```python
    # Build at_a_glance from the LLM's selection; join content from desk items.
    result["at_a_glance"] = _join_at_a_glance(result["at_a_glance"], domain_analysis)
```
Remove `normalize_tag` and `tag_label` from `_override_counts` initialization (lines ~607–612) since neither override exists anymore; keep `recompute_source_depth`, `ensure_primary_glance_coverage`, and `overlap_downgrade`. Update any test in `tests/test_cross_domain.py` that asserted on `_override_counts["normalize_tag"]` / `["tag_label"]` to drop those keys (grep first).

Then delete `_normalize_tag` (parse.py:182), `_TAG_KEYWORDS` (40–150), and `_VALID_TAGS` (12–25) **iff** no longer referenced. Verify:
```bash
docker run --rm -v "$PWD":/app morning-digest-dev grep -rn "_normalize_tag\|_TAG_KEYWORDS\|_VALID_TAGS" --include=*.py .
```
If `morning_digest/validate.py:228-231` still references a tag fallback against `VALID_TAGS`, that now comes from `morning_digest.tags.VALID_TAGS` (Task 4) and is defensive-only — leave it but add a comment: `# Defensive: tag is desk-derived upstream; this guards malformed artifacts only.`

`_fallback_glance_item` (parse.py:305) already sets `tag_label` via `_TAG_LABELS[tag]` — now the shared map; leave it.

- [ ] **Step 6: Update the execute prompt schema**

In `prompts/cross_domain_execute.md`:
- Replace rule line 21 (`Preserve domain analysts' item_id, facts, and analysis verbatim…`) with:
  `Select at_a_glance items by \`item_id\`; the pipeline joins headline, facts, analysis, links, and tag from the domain analysis automatically. Your contribution is the selection itself, its order (most important first), and the \`cross_domain_note\`.`
- Replace the `at_a_glance` schema block (lines 43–56) with:
  ```
  "at_a_glance": [
    {
      "item_id": "stable ID copied exactly from a domain analysis item",
      "cross_domain_note": "1-2 sentences connecting this item across desks, or null"
    }
  ],
  ```
- Remove the now-stale rule line 91 (`The \`tag\` field must use only the exact allowed vocabulary…`) and the line referencing `tag` must-be-exactly-one-of.

- [ ] **Step 7: Make the contracts normalizer tolerate the minimal shape**

In `morning_digest/contracts.py` `_normalize_at_a_glance_entries` (681–741): the normalizer currently `_to_str`-coerces `tag`/`tag_label`/`facts`/`analysis`/`source_depth` from the raw LLM item. After the join those fields are populated by code in `_validated_output`, **but** `normalize_cross_domain_output_artifact` runs in `stage.py:174` *before* `_validated_output` (stage.py:187). So at normalize time the raw items only have `{item_id, cross_domain_note}`. Confirm the normalizer tolerates missing fields (it already defaults via `item.get(...)` → empty string) — it does; no change required beyond a confirming test:

```python
# tests/test_cross_domain_two_turn.py  (or test_contracts.py)
def test_at_a_glance_normalizer_tolerates_minimal_selection_shape():
    from morning_digest.contracts import normalize_cross_domain_output_artifact

    raw = {"at_a_glance": [{"item_id": "ai_tech-x", "cross_domain_note": "note"}]}
    out, issues = normalize_cross_domain_output_artifact(raw)
    entry = out["at_a_glance"][0]
    assert entry["item_id"] == "ai_tech-x"
    assert entry["cross_domain_note"] == "note"
    assert entry["facts"] == ""  # joined later in _validated_output, empty here
```

- [ ] **Step 8: Run the cross_domain + contracts + two-turn suites**

Run: `pytest tests/test_cross_domain.py tests/test_cross_domain_two_turn.py tests/test_contracts.py -v`
Expected: PASS. Update any characterization tests that asserted the LLM-emitted `tag`/`facts` were preserved verbatim — the new contract is selection-join (these are intended behavior changes; rewrite the assertions to expect joined values, do not weaken them).

- [ ] **Step 9: Full regression + lint**

Run: `pytest tests/ -q && ruff check .`
Expected: PASS. The biggest blast radius is here; fix fallout before committing.

- [ ] **Step 10: Commit**

```bash
git add prompts/cross_domain_execute.md cross_domain/parse.py morning_digest/contracts.py tests/
git commit -m "refactor(cross_domain): at_a_glance selection-join; derive tag from desk, drop verbatim copy + _normalize_tag (Appendix A #2, #3)"
```

---

## Task 6: Derive `domains_bridged` from `further_reading` (#12)

**Why:** Appendix A #12. Each deep dive emits `domains_bridged` that nothing validates; `anomaly.py:218` consumes it on trust. It is mechanically derivable from which desks supplied the dive's `further_reading` URLs. Drop it from the schema; derive in code.

**Files:**
- Modify: `prompts/cross_domain_execute.md` (remove `domains_bridged` from deep-dive schema, line 64)
- Modify: `cross_domain/parse.py` (new `_derive_domains_bridged`; call in `_validated_output`)
- Test: `tests/test_cross_domain.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cross_domain.py
def test_domains_bridged_derived_from_further_reading():
    from cross_domain.parse import _derive_domains_bridged

    domain_analysis = {
        "geopolitics_events": {"items": [
            {"item_id": "geopolitics_events-1", "links": [{"url": "https://reuters.com/x"}]},
        ]},
        "defense_space": {"items": [
            {"item_id": "defense_space-1", "links": [{"url": "https://janes.com/y"}]},
        ]},
    }
    result = {"deep_dives": [
        {"headline": "H", "further_reading": [
            {"url": "https://reuters.com/x"}, {"url": "https://janes.com/y"},
        ]},
    ]}
    _derive_domains_bridged(result, domain_analysis)
    assert set(result["deep_dives"][0]["domains_bridged"]) == {"geopolitics_events", "defense_space"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cross_domain.py::test_domains_bridged_derived_from_further_reading -v`
Expected: FAIL — `_derive_domains_bridged` does not exist.

- [ ] **Step 3: Implement the derivation**

In `cross_domain/parse.py`:
```python
def _url_to_desk(domain_analysis: dict) -> dict[str, str]:
    """Map each source URL to the desk whose items reference it."""
    mapping: dict[str, str] = {}
    for desk_key, domain_result in domain_analysis.items():
        if not isinstance(domain_result, dict):
            continue
        for item in domain_result.get("items", []) or []:
            for link in item.get("links", []) or []:
                url = str(link.get("url", "")).strip()
                if url:
                    mapping.setdefault(url, desk_key)
    return mapping


def _derive_domains_bridged(result: dict, domain_analysis: dict) -> None:
    """Set each deep dive's domains_bridged from the desks of its further_reading URLs."""
    url_desk = _url_to_desk(domain_analysis)
    for dive in result.get("deep_dives", []) or []:
        desks: list[str] = []
        for link in dive.get("further_reading", []) or []:
            desk = url_desk.get(str(link.get("url", "")).strip())
            if desk and desk not in desks:
                desks.append(desk)
        dive["domains_bridged"] = desks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cross_domain.py::test_domains_bridged_derived_from_further_reading -v`
Expected: PASS

- [ ] **Step 5: Wire into `_validated_output`**

In `_validated_output`, after the `further_reading` URL-pruning loop (parse.py ~646–651) and before the source_depth/cap logic, add:
```python
    _derive_domains_bridged(result, domain_analysis)
```
(Derive after pruning so only known URLs contribute.) Remove `"domains_bridged": ["geopolitics_events", "defense_space"]` from the execute prompt schema, line 64 of `prompts/cross_domain_execute.md`.

- [ ] **Step 6: Run affected suites**

Run: `pytest tests/test_cross_domain.py tests/test_stages.py -k "domain or anomaly or cross" -v`
Expected: PASS. Confirm `anomaly.py:218` still reads a populated list on a dry-run artifact.

- [ ] **Step 7: Commit**

```bash
git add prompts/cross_domain_execute.md cross_domain/parse.py tests/test_cross_domain.py
git commit -m "refactor(cross_domain): derive domains_bridged from further_reading desks; drop from LLM schema (Appendix A #12)"
```

---

## Task 7: Seam-links documentation cleanup (#4)

**Why:** Appendix A #4. `seams.py:344-365` (`_links_by_item_id`) builds the authoritative evidence links from `domain_analysis` and `seams.py:444` writes them regardless of LLM output. The prompt should not imply LLM-supplied URLs are kept. Documentation/comment only — no behavior change.

**Files:**
- Modify: `prompts/seam_annotations.md` (clarify evidence excerpts are not URLs the pipeline keeps)
- Modify: `stages/seams.py` (comment on `_links_by_item_id` authority)

- [ ] **Step 1: Add the prompt note**

In `prompts/seam_annotations.md`, under the "Hard evidence gate" section (after line 36), add:
`- Do not emit URLs. The pipeline attaches the authoritative source links per item from the domain analysis; your evidence is the source name, excerpt, and framing only.`

- [ ] **Step 2: Add the code comment**

In `stages/seams.py` above `_links_by_item_id` (line 344), add:
```python
# Authoritative: seam annotation links come from domain_analysis, not the LLM.
# The prompt deliberately does not ask for URLs (see prompts/seam_annotations.md).
```

- [ ] **Step 3: Confirm no behavior change**

Run: `pytest tests/ -k seam -v`
Expected: PASS (docs/comments only).

- [ ] **Step 4: Commit**

```bash
git add prompts/seam_annotations.md stages/seams.py
git commit -m "docs(seams): clarify evidence links are pipeline-supplied, not LLM (Appendix A #4)"
```

---

## Task 8: Full regression + dry-run inspection

**Why:** The epic's verification standard for Phase 1 is spot-check of test runs, not diff-match. Confirm the suite is green and a dry run produces reasonable cross_domain/seams output under the new contract.

**Files:** none (verification only).

- [ ] **Step 1: Full suite + lint**

Run:
```bash
docker run --rm -v "$PWD":/app morning-digest-dev pytest tests/ -q
docker run --rm -v "$PWD":/app morning-digest-dev ruff check .
```
Expected: all green. Fix any residual failures before proceeding.

- [ ] **Step 2: Dry-run inspection against frozen artifacts**

Run the cross_domain stage over the frozen baseline fixture and eyeball the output:
```bash
docker run --rm -v "$PWD":/app morning-digest-dev python pipeline.py --stage seams --dry-run
```
Inspect `output/.../cross_domain_output.json`: confirm `at_a_glance` items carry joined `facts`/`analysis`, `tag` matches the desk-of-origin, `tag_label` is correct, `domains_bridged` on deep dives is populated from desks, and no item carries a fabricated/mismatched tag. Note observations in the PR description.

- [ ] **Step 3: Commit any fixups** (if Step 1/2 required code changes)

```bash
git commit -am "fix(cross_domain): address PR-A regression fallout"
```

---

## Task 9: Record Appendix A dispositions

**Why:** Epic success criterion #1 requires every Appendix A finding be marked removed or moved to the "not doing on purpose" bucket with a one-line reason. PR-A is the bookkeeping vehicle.

**Files:**
- Modify: `docs/exploration/lemongraph-seams-assessment.md` (annotate Appendix A)

- [ ] **Step 1: Annotate each finding's disposition**

In `docs/exploration/lemongraph-seams-assessment.md`, add a `> **Disposition (PR-A, 2026-06-02):**` line under each Appendix A finding:
- #1 tag_label — **removed** (Task 4: shared `TAG_LABELS`, derived in code; dropped from execute schema in Task 5).
- #2 tag — **removed** (Task 5: derived from desk-of-origin via join; `_normalize_tag`/`_TAG_KEYWORDS` deleted).
- #3 verbatim copy — **removed** (Task 5: selection-join).
- #4 seam links — **removed** (Task 7: doc/comment; code was already authoritative).
- #5 exactly-N — **removed** (Task 2: prompts relaxed to "up to N").
- #6 cross-desk `linked_item_ids ≥ 2` — **deferred to PR-D/PR-I** (graph candidate generation).
- #7 seam evidence gate — **deferred to PR-D/PR-I** (graph constraint).
- #8 per-outlet caps (3 impls) — **deferred to PR-C** (consolidate to assemble).
- #9 coverage_gaps "max 5" — **not doing** (coverage_gaps stage is being deleted wholesale; epic dead-code removals).
- #10 per_item "at most 6" — **removed** (Task 3: prompt cap dropped).
- #11 `_ensure_primary_glance_coverage` — **deferred to PR-D** (inverted index makes it deterministic).
- #12 domains_bridged — **removed** (Task 6: derived from further_reading desks).
- #13 same-event merge safety net — **deferred to PR-E** (clustering pre-pass).
- #14 source_depth desk label — **deferred to PR-E** (settle `_recompute_source_depth` on cluster form once).
- #15 compress.py target-words (LOW) — **not doing now** (outside the named regex sweep; revisit if compression length drifts). Note the named sweep target `_HEDGED_SEAM_RE` was **removed** (Task 1).

- [ ] **Step 2: Commit**

```bash
git add docs/exploration/lemongraph-seams-assessment.md
git commit -m "docs(assessment): record Appendix A dispositions after PR-A"
```

---

## Task 10: Re-capture PR-B prompt baseline + finish

**Why:** PR-A intentionally changed prompt text (`cross_domain_execute.md`, `cross_domain_plan.md`, `seam_annotations.md`), invalidating the PR-0 baseline. PR-B diffs rendered prompts against this baseline expecting byte-identity post-threading, so it must reflect post-PR-A prompts. Requires `FIREWORKS_API_KEY` in the environment.

**Files:**
- Modify: `output/prompt_baseline/*.txt` (re-captured), `docs/prompt-baseline-README.md` (note the PR-A refresh), `TODO.md`

- [ ] **Step 1: Re-capture the baseline**

```bash
docker run --rm -e FIREWORKS_API_KEY -v "$PWD":/app morning-digest-dev \
  python pipeline.py --stage seams --dry-run --capture-prompts output/prompt_baseline/
git add -f output/prompt_baseline/
```
Confirm `seams__01.txt`, `cross_domain__01.txt`, `cross_domain__02.txt` reflect the new at_a_glance selection schema (no `tag`/`tag_label`/`domains_bridged` request; "up to N" wording).

- [ ] **Step 2: Note the refresh in the README**

In `docs/prompt-baseline-README.md`, under "What was captured here", add: `Re-captured after PR-A (2026-06-02), which changed the execute/plan/seam prompts — the baseline now reflects the selection-join schema and "up to N" quotas.`

- [ ] **Step 3: Check off the TODO**

In `TODO.md`, change `- [ ] **PR-A** — …` to `- [x] **PR-A** — …`.

- [ ] **Step 4: Final commit + PR**

```bash
git add output/prompt_baseline/ docs/prompt-baseline-README.md TODO.md
git commit -m "chore(pr-A): re-capture prompt baseline post-prompt-changes; check off PR-A"
git push -u origin pr-A-override-removal
```
Open the PR via `commit-commands:commit-push-pr` or `gh pr create`, body summarizing the dispositions table from Task 9 and the dry-run observations from Task 8.

---

## Self-review checklist (run before execution)

- **Spec coverage:** #1✓(T4,T5) #2✓(T5) #3✓(T5) #4✓(T7) #5✓(T2) #10✓(T3) #12✓(T6) regex-sweep✓(T1). Deferred findings recorded (T9). PR-B baseline refresh (T10). ✅
- **Ordering:** independent prompt edits (T1–T3) → shared map (T4) → join that depends on the map (T5) → derivation (T6) → docs (T7,T9) → verify (T8) → baseline (T10). ✅
- **Type consistency:** `label_for_tag`/`TAG_LABELS`/`desk_tag_set` defined in T4 and used in T5; `_join_at_a_glance`/`_derive_domains_bridged`/`_index_domain_items`/`_url_to_desk` all defined where called. ✅
- **No placeholders:** every code step shows complete code; every command shows expected result. ✅
