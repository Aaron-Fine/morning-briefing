# Morning Digest — TODO

Last updated: 2026-06-09

> **Design-intent note.** When triaging items marked "stale" or "unused,"
> first ask whether the feature was *intentional but silently broken* (e.g.
> Gmail stripping positioning). If so, restore — don't delete. The AQI
> overlay (restored 2026-04-17) is a canonical example. This heuristic
> outlives any particular plan; keep it at the top of whatever TODO replaces
> this one.

---

## Active plan

The current body of work is the **Graph-Shaped Substrate and Seams
Reconstruction** epic:
`docs/superpowers/plans/2026-05-24-Graph-Epic.md`, based on the assessment in
`docs/exploration/lemongraph-seams-assessment.md` (its Appendix A is the
master override-removal checklist).

The epic redraws the Python/LLM boundary: remove deterministic-override
sprawl, promote `connection_hooks` to an inverted index for cross-desk
reasoning, add article clustering, make `config/audience.yaml` the single
source of truth for personalization, and reconstruct seams. The pipeline is
**not running daily right now by choice**; only test-data runs
(`pipeline.py --dry-run`) exist until Phase 4/5.

## Pre-implementation prep

- [x] Review and tighten the epic (regression bar, gate philosophy, feature
      flags, model strategy, success-criterion operational test).
- [x] Commit the reference files the epic points at (assessment +
      `config/audience.yaml` draft).
- [x] Re-validate Appendix A override findings against HEAD (all 15 still
      exist; line numbers drift — grep by symbol at PR time).
- [x] Replace the stale personalization "five files" claim with the real
      ~dozen-file inventory (mostly prompt markdown) — see PR-B.
- [x] Expand PR-0 into a per-run observability artifact (`run_meta.json` →
      `metrics`)
      that feeds every later keep-or-drop decision.
- [x] **PR-0 leads Phase 1** — built up front (observe-only), extended by
      later phases. The PR-B rendered-prompt baseline is captured at the *end
      of PR-0* (instrumentation doesn't touch prompt text, so the baseline is
      clean and exists before any PR-B threading begins).

## Next: Phase 1 (structural cleanup)

PR-0 (merged 2026-06-02, PR #2) and PR-A (merged 2026-06-07, PR #3) have
landed. PR-B and PR-C are order-independent; **PR-B is next** — its
rendered-prompt baseline was re-captured post-PR-A and is current. See the
epic for detail.

- [x] **PR-0** — per-run observability in `run_meta.json` (`metrics` key:
      per-stage cost/usage, override firing counts, item-flow,
      domain_research loop). PR-B rendered-prompt baseline captured at the
      end (`output/prompt_baseline/`, see `docs/prompt-baseline-README.md`).
- [x] **PR-A** — work the Appendix A override checklist; drop `tag_label`,
      derive `tag` from desk-of-origin, switch cross_domain to item_id
      selection, relax "exactly N" → "up to N", regex sweep. Dispositions
      recorded in the assessment's Appendix A.
- [ ] **PR-B** — `audience.yaml` as single source of truth; thread into the
      ~dozen files in the inventory (mostly prompts). Prompt-diff verification.
- [ ] **PR-C** — consolidate per-outlet caps to assemble; reliability-tier
      propagation.
- [ ] Dead-code removals (`_rebalance_categories`, assemble Phase 1 fallback,
      `briefing_packet`, `coverage_gaps`, never-built `audit_provenance`).

Phases 2–5 are detailed in the epic and not expanded here until Phase 1 lands.

---

## Open deferred cleanup (carried over, not yet done)

- **Extract retry backoff helper.** `morning_digest/llm.py::_retry_loop` and
  `pipeline.py` both implement exponential backoff with jitter. Consolidate
  into one helper when retry policy is next touched.
- **Timezone/date audit.** Confirm `TZ` authority, shared-helper adoption,
  artifact dates, and user-visible date formatting. Revisit only if date
  drift appears in artifacts or rendered email.
- **Residual coverage-gap source depth.** Recurring specialist gaps (NPT/AI
  governance, DPRK posture, European LNG, maritime insurance, Taiwan Strait
  monitoring) persisted in the last dry runs. Note: the epic *drops*
  `coverage_gaps` entirely, so this becomes a sourcing question
  (`config/sources.yaml`), not a stage-diagnostic one.

---

## Completed work

The **source-quality and downstream-selection plan** (2026-05-01) completed
in full — collect-stage failure visibility, source-health classifications,
feed audit/curation, tiered enrichment, distinct-source hardening, the
`perspective` mini-desk, and category quotas. See git history (commits
through `0f064c3`) and the prior revision of this file for the detailed
checklist. The earlier seams + weekly-spiritual rework (2026-04-18) also
landed; its still-relevant design constraints were folded into the Graph
Epic's Phase 4 (PR-I) before its plan doc was retired.

For the full history of bug fixes, weather-module phases, and test-coverage
work, see the git log.
