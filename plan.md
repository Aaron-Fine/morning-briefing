# Morning Digest — Seams rework + Weekly spiritual artifact

**Date drafted:** 2026-04-18
**Status:** Ready for agent implementation
**Assumes:** Implementing agent reads current codebase before acting. Paths and function signatures below are targets, not claims about current state.

---

## Architectural intent (read before executing any epic)

Two shifts worth stating up front, because they should guide judgment calls that aren't covered by epic-level acceptance criteria. If an implementation decision seems ambiguous, fall back to these.

**Seams is being promoted from a section to a reviewer.** The current seams stage produces a bag of findings rendered as their own section — skippable, and often skipped. The rework makes seams produce per-item annotations that render inline on the at-a-glance stories they contest. The cost this incurs: failure modes that were previously contained to one skippable section now potentially poison every item. The mitigation is two load-bearing disciplines — the evidence gate (every seam cites ≥2 contrasting sources) and the novelty filter (reject "sources disagree on contested topic"). These are not optional polish; they're what makes the promotion survivable.

**The spiritual stage is being split into a weekly generator and a daily reader.** The current prepare_spiritual stage regenerates reflections daily from a small anchor, producing near-identical output all week. The rework pushes expensive work to a weekly stage that consumes the user-authored study guide and emits a structured artifact; the daily stage reads a slice. The weekly artifact's schema should be durable — the study-guide writing process may later consume prior weeks' artifacts as context, so schema changes are expensive. Get it right on first pass rather than iterating aggressively.

Both reworks deliberately reject tempting shortcuts: seams does *not* gain a "stateful mode" that reads prior days (deferred), and the spiritual stage does *not* attempt to bridge scripture to news headlines (architecturally rejected — tone is set by *disposition*, not by forced parallels).

---

## Epic 1 — Seams taxonomy and per-item schema

Rewrite `stages/seams.py` to emit per-item annotations rather than a flat findings list.

### Input contract

Seams consumes output of `stages/analyze_domain.py` (four desks: geopolitics, defense/space, AI/tech, economics) plus raw source snippets from prior stage artifacts. Each desk produces at-a-glance items with stable IDs; seams annotates those items.

Confirm the current item-ID scheme before implementation. If items don't have stable IDs across stages, adding them is part of this epic.

### Output schema

Write a structured JSON artifact at `output/artifacts/YYYY-MM-DD/seam_annotations.json`:

```json
{
  "per_item": [
    {
      "item_id": "geopol-001",
      "seam_type": "framing_divergence",
      "one_line": "The non-Western read: this is escalation. Wire coverage: signaling.",
      "evidence": [
        {"source": "Reuters", "excerpt": "...", "framing": "deterrence signaling"},
        {"source": "Global Times", "excerpt": "...", "framing": "escalation"}
      ],
      "confidence": "high"
    }
  ],
  "cross_domain": [
    {
      "seam_type": "cross_desk",
      "one_line": "AI/tech reads hardware demand as bullish; geopolitics reads the same supply as chokepoint risk.",
      "linked_item_ids": ["ai-003", "geopol-007"]
    }
  ]
}
```

Cross-domain seams are captured in the artifact but not rendered by Epic 2 — they're preserved for debugging and potential future surfacing. See "Explicit non-goals."

### Seam type taxonomy

Five types, detected by a single unified prompt that teaches all of them with positive and negative examples per type. Each annotation's `seam_type` field is typed against this enum:

- `framing_divergence` — sources agree on facts, disagree on frame, protagonist, or category of event
- `selection_divergence` — one side silent where coverage is expected; the gap itself is the story
- `causal_divergence` — event and magnitude agreed; mechanism or attribution contested
- `magnitude_divergence` — coverage universal, but significance contested
- `credible_dissent` — consensus exists, but a non-fringe counter-voice has a coherent case

All five types share a property: they're grounded in today's sources disagreeing about today's events. `embedded_premise` was deliberately excluded — it's the assumption-tracking failure mode relocated, and assumption tracking is deferred. See "Explicit non-goals."

### Anti-invention discipline

Two hard constraints, structural — not polish:

1. **Evidence gate.** Every `per_item` annotation must cite ≥2 distinct sources whose excerpts, read together, make the contested framing legible to a skeptical reader. If the model cannot produce two excerpts, drop the annotation. Enforce in the prompt *and* in a post-generation validator.

2. **Novelty filter.** Explicitly reject annotations that reduce to "sources have different opinions on a politically contested topic." The prompt should teach that signal lives in contestation of what should be settled, or consensus on what should be contested. Include 2–3 negative examples in the prompt.

### "Why now" guidance for item selection

This is not a seams concern but a desk-level one. As part of Epic 1, add prompt guidance to `stages/analyze_domain.py` that anchors each desk's item selection in today-specific reasoning.

The prompt should ask, for each at-a-glance item: "What specifically about today makes this included — or, if nothing specifically today, what's the cumulative state that earned inclusion now." The second half legitimizes trend-inclusion rather than forcing a manufactured news hook.

This guidance shapes selection and the existing "why" field each desk produces. No new artifact field, no rendering change.

### Cost-bearing prioritization

Per the three-layer framework ("ideology sets the menu, money picks the meal, costs are distributed downward"), prefer seam annotations where contested framing materially determines who bears the cost of the interpretation. Prompt-level guidance, not a hard filter.

### Voice

The prompt should produce named-perspective phrasing — "The non-Western read:" / "A skeptical economics read:" — rather than hedged attribution ("some analysts argue"). This is Epic 1's responsibility; Epic 2 only enforces that named-perspective phrasing survives to render.

### Model assignment

Claude Sonnet. Cost justified — this is the stage where sycophancy and confabulation would be most damaging.

### Acceptance

- `seam_annotations.json` produced for ≥3 consecutive real pipeline runs
- ≥80% of `per_item` annotations pass the evidence gate on first generation (2+ sources, quoted excerpts present)
- Manual review of one week's output shows ≥1 annotation per desk on most days, and zero days where the pipeline fabricates cross-source disagreement not present in input
- Desk outputs show noticeably stronger today-specific reasoning in their "why" fields after the "why now" prompt guidance lands
- Schema consumed correctly by Epic 2

### Commit intent

> **seams: per-item annotations with five-type taxonomy and evidence gate**
>
> Replaces flat findings list with structured per-item annotations tied to at-a-glance item IDs. Five-type taxonomy (framing, selection, causal, magnitude, credible dissent) detected by a single unified prompt. Evidence gate requires ≥2 sourced excerpts per annotation; novelty filter rejects "sources disagree on contested topic"; cost-bearing prioritization prefers annotations where framing determines who pays. Also adds "why now" prompt guidance to analyze_domain for today-specific item selection.
>
> Architectural intent: seams is now a reviewer, not a section. Failure modes contained by evidence discipline rather than by visual isolation from the rest of the brief. `embedded_premise` deliberately excluded as relocated assumption-tracking.

---

## Epic 2 — Inline rendering

Modify `stages/assemble.py` and `templates/email_template.py` to render seam annotations inline on at-a-glance items. Remove the standalone seams section.

### Rendering rules

- Annotation renders **immediately below** the at-a-glance item it's attached to
- Typographically subordinate: smaller, italic or indented, de-emphasized color — but semantically parallel (a different voice, not a disclaimer)
- Voice gate: if the incoming `one_line` starts with hedged phrasing ("some analysts argue", "critics say", etc.) without a named perspective, log a warning — Epic 1's prompt should prevent this, but don't let it through silently
- Hard cap: one annotation per at-a-glance item. If seams produced multiple for the same item, take the highest-confidence and drop the rest (surface the others in the artifact for debugging, not in the email)
- One line only. If `one_line` exceeds ~220 characters, truncate at sentence boundary
- `cross_domain` seams in the artifact are **not rendered**. They stay available for debugging and future use

### Dark mode

- Annotations must use the existing `--wx-*` CSS variable pattern with hardcoded fallbacks
- Verify rendering in Proton Mail, Apple Mail, Gmail, and Outlook — Gmail and Outlook don't support `prefers-color-scheme`, so the light-mode fallback must be legible

### Acceptance

- Visual diff from a pre-rework digest: no separate seams section, annotations inline on at-a-glance items
- No visible cross-domain capstone in the email; cross-domain seams still populate the artifact
- Dark mode renders correctly in all four target clients

### Commit intent

> **assemble: inline seam annotations**
>
> Removes standalone seams section. Per-item annotations render subordinate-but-parallel to their at-a-glance items. Cross-domain seams stay in the artifact but are not surfaced in the email — preserved for possible future rendering.
>
> Architectural intent: contestation arrives with the news it contests, not separately. A seams section that gets skipped stops doing work; an inline annotation can't be skipped without skipping the story itself.

---

## Epic 3 — Weekly spiritual artifact generator

New stage: `stages/prepare_spiritual_weekly.py`.

### Trigger

Runs on the first pipeline execution of each week. Inherit the week boundary from existing CFM logic in `sources/come_follow_me.py` (verify before implementation — do not assume Sunday). On non-first-of-week runs, this stage is a no-op.

### Input

User-authored weekly study guide at `state/spiritual/weekly/YYYY-MM-DD.md` where the date is the week's start date. The guide follows the user's existing section structure, including section 6 (Current Event Mapping — Use and Misuse), with parts A (misuse in discourse) and B (faithful application).

If the guide file is missing for the current week: log a warning, write an empty/minimal artifact noting the absence, and skip gracefully. Epic 4's daily stage handles missing-artifact fallback.

### Output schema

Write to `output/artifacts/spiritual/YYYY-MM-DD_weekly.json`. **This schema should be durable — future changes are expensive.**

```json
{
  "week_start": "2026-04-19",
  "cfm_range": "D&C 76",
  "weekly_purpose": "...from study guide's stated purpose...",
  "daily_foci": [
    {
      "id": "focus-1",
      "text_ref": "D&C 76:22-24",
      "guide_excerpt": "The paragraph or two from the user's guide the daily reflection should draw from."
    }
  ],
  "misuses": [
    {
      "text": "D&C 76:103",
      "common_use": "...",
      "correction": "...",
      "cost_bearer": "..."
    }
  ],
  "applications": [
    {
      "question_or_insight": "...",
      "grounding": "..."
    }
  ],
  "conspicuous_absences": [
    "..."
  ],
  "proposed_sequence": {
    "monday": "focus-1",
    "tuesday": "focus-2",
    "wednesday": "focus-3",
    "thursday": "focus-4",
    "friday": "focus-5",
    "saturday": "focus-6"
  }
}
```

`proposed_sequence` is a flat day-of-week → focus-id map. No arc-specific special cases — the user can reshape the sequence over time once patterns become clear.

### Proposed sequence

The stage produces a suggested day-to-focus mapping but does not prescribe a rigid arc. The user can edit `proposed_sequence` in the artifact before or during the week; Epic 4 reads the live file on each daily run.

### Model assignment

Claude Sonnet. Low frequency (weekly), synthesis-heavy, consumes human-authored content that deserves careful reading. Cost is negligible at weekly cadence.

### Acceptance

- For ≥2 weeks of real study guides, artifact generates successfully and populates all required fields
- `proposed_sequence` references only valid `daily_foci` IDs
- Schema stable across runs (no field renames between weeks)
- Missing guide file logs warning, writes minimal artifact, exits cleanly

### Commit intent

> **spiritual: weekly artifact generator from user study guide**
>
> New weekly stage consumes `state/spiritual/weekly/*.md` and emits a structured artifact with daily foci, misuse flags, faithful applications, conspicuous absences, and a proposed daily sequence. Schema designed to be durable — may later be consumed by the study-guide writing process as prior-week context.
>
> Architectural intent: amortize the study guide across the week rather than regenerating reflections from scratch daily. Moves expensive synthesis off the daily critical path.

---

## Epic 4 — Daily spiritual stage rewrite

Rewrite `stages/prepare_spiritual.py` to consume the weekly artifact.

### Behavior

1. Read the most recent `*_weekly.json` from `output/artifacts/spiritual/` where `week_start` ≤ today. Read the file fresh on each daily run — no cached copy — so user edits to `proposed_sequence` mid-week are respected
2. Determine today's focus ID from `proposed_sequence` keyed by day of week. If the ID is invalid (references a `daily_foci` entry that doesn't exist), fall back to the next valid focus and log the invalid reference
3. Write a short daily reflection (~80–150 words) grounded in the focus's `guide_excerpt` and any directly-related misuses/applications from the weekly artifact
4. **Do not attempt to connect the reflection to today's news items.** Architectural posture: spiritual tone is set by *disposition* (text-first, rigorous, willing to name misuse), not by thematic bridging to headlines

### Fallback behavior

If no weekly artifact exists for the current week, or the artifact exists but is the empty/minimal form (guide was missing), fall back to the current prepare_spiritual behavior. Log that fallback occurred and which case triggered it.

### Model assignment

Kimi K2.5. Most reasoning lives in the weekly artifact; the daily stage is surfacing a slice and writing short prose.

### Acceptance

- Daily reflections vary across a week when the weekly artifact is present (manual review of one week — reflections should reference different text_refs and guide excerpts)
- User edits to `proposed_sequence` mid-week take effect on the next daily run
- When guide absent, falls back gracefully and digest still sends
- Reflection never attempts explicit news-to-scripture mapping — manual review of a week's output for phrases like "just as today's events", "similarly, in the news", or other bridging language

### Commit intent

> **spiritual: daily stage reads weekly artifact slice**
>
> Daily spiritual stage becomes a reader of the weekly artifact, selecting today's focus from the proposed sequence. Reads artifact fresh on each run so user edits to the sequence are respected. Explicitly resists thematic bridging between scripture and news — tone is set by disposition, not by forced parallels.
>
> Falls back to legacy behavior when weekly guide absent, so the digest never fails on a guide-less week.

---

## Implementation sequencing

Epics 1→2 form one dependency chain (seams). Epics 3→4 form another (spiritual). Chains are independent — safe to parallelize across two agents or two branches.

Within each chain:

- **Epic 1** and **Epic 3** are load-bearing; their output schemas constrain downstream epics
- **Epics 2 and 4** are shorter and their shape is determined by the schemas above them

Each epic should land as a distinct commit using the `Commit intent` drafts above (paraphrased as needed). The architectural-intent sentences in those drafts should survive to the commit message — they're what future agents will read when deciding whether to undo something.

---

## Explicit non-goals

These are out of scope for this plan. If a natural implementation path suggests doing any of them, stop and flag.

- **Stateful/longitudinal seams** (reading prior days' seam output) — deferred.
- **Assumption register automation** and the `embedded_premise` seam type — deferred, pending several months of manual observation to calibrate what shape real load-bearing assumptions take. The `embedded_premise` type was deliberately cut from the taxonomy to keep the deferral consistent.
- **Cross-domain seams rendering** — detection runs and populates the artifact, but no email surfacing. Revisit only if manual review shows real cross-desk patterns being missed.
- **Self-consistency check between synthesis and seam annotations** — not implemented preemptively. Revisit if inline rendering reveals synthesis asserting as fact what seams flagged as contested.
- **Any explicit news-to-scripture bridging** — architecturally rejected, not deferred. If an implementation drifts toward this, it is wrong.
- **Three Lens framing as a rendered feature** — deferred until the framework stops evolving. The framework can inform prompts (cost-bearing prioritization in Epic 1) but does not surface as labeled structure in the email.
- **Reader-context / current-concerns file** — deferred until the rework is lived with and a concrete need emerges.
- **Deep-dive criterion rework** (belief-shift framing) — deferred as follow-on work.
- **Changes to the four specialist desks in `analyze_domain`** beyond the "why now" prompt guidance in Epic 1 — out of scope.
- **Changes to source categorization** (`non-western`, `perspective-diversity`, etc.) — out of scope.
- **UI changes beyond what Epic 2 requires.**
- **Model swaps** — keep Claude Sonnet on seams and weekly spiritual; keep Kimi on daily spiritual. If cost becomes a concern, revisit as a separate plan.
