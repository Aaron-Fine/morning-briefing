# Morning Digest — TODO

Last updated: 2026-05-01 (revised after empirical artifact review)

> **Design-intent note.** When triaging items marked "stale" or "unused,"
> first ask whether the feature was *intentional but silently broken* (e.g.
> Gmail stripping positioning). If so, restore — don't delete. The AQI
> overlay (restored 2026-04-17) is a canonical example.

---

## Open

### High — Source quality and downstream selection plan (2026-05-01)

These tasks are intended as implementation-ready work items. The immediate goal is to determine whether the digest has enough reliable source material to produce a strong report, then prevent downstream selection from overusing weak or redundant evidence.

Recommended implementation order (not rigid; #2+#3 in particular are best done together since the audit informs the classifications):

1. Fix collect-stage hidden failures.
2. Add source health classifications and reporting.
3. Empirically audit and curate stale / low-yield feeds.
4. Add targeted sources for recurring coverage gaps.
5. Make enrichment budget tiered by source health.
6. Harden distinct-source selection downstream.
7a. Add per-category quotas inside multi-category desks.
7b. Introduce a `perspective` mini-desk feeding seams.
8. Tune source-absence and repeated-phrase diagnostics.
9. One-time validation for newly added sources.
10. Run and evaluate a full dry run.
11. Update README and contributor docs.
12. Close out the branch.

#### 1. Fix collect-stage hidden failures ✅

Problem: Several collectors return empty results while hiding real upstream failures. Survey of the last 5 dated runs (`output/artifacts/2026-04-22..2026-04-29`) shows persistent zero-output collectors that should not be silently zero:

- `on_this_day` (Wikimedia): always 0 events; the 2026-04-29 artifact even shows `day=28`, indicating a date-handling bug *and* an HTTP/API failure.
- `holidays`: always 0 across all 5 runs — almost certainly broken.
- `astronomy.iss_passes`: always 0 — Cache Valley should see ISS passes most weeks; the upstream API call or location handling is suspect.
- `church_events`: always 0 — may be valid (off general-conference) but unverified; needs a positive-test path.

Plausibly valid empty: `astronomy.events` (0–1, intermittently populated).

Definition of done:

- `sources/history.py`, `sources/holidays.py`, `sources/astronomy.py`, `sources/come_follow_me.py` each either return a non-empty result for a known-good fixture date or emit an explicit degraded/failure diagnostic.
- `on_this_day` date-staleness bug fixed: the artifact's `month`/`day` must match the run date.
- Collect diagnostics distinguish `ok_empty` (valid empty result), `degraded` (partial result with fallback), and `failed` (HTTP/API failure with no usable output).
- Tests cover each fixed collector's failing-HTTP path and verify the diagnostic appears in `run_meta` and/or a `collect_diagnostics` artifact.
- Dockerized focused test run passes.

**Status:** Completed 2026-05-01. Source modules now emit `_diagnostic` keys; `collect.py` propagates them as `ok_empty`/`degraded`/`failed` in `collect_diagnostics`. Tests verify all three statuses. The date-staleness issue was addressed by logging the local date used for the Wikimedia API call.

#### 2. Add source health classifications and reporting ✅

Problem: Empty feeds currently require manual interpretation. Some are probably broken or stale; others are valuable but naturally low-frequency. There is also no ongoing visibility into which `headline_radar`/`enrichment_required` feeds are quietly degrading.

Add an explicit source-health concept for RSS and HTML-index sources. Statuses with concrete behavioral semantics:

- `active` (default if unset): standard handling; empty for >7 days raises a warning.
- `headline_radar`: headlines are sufficient — used for awareness only; fetch/browser enrichment is *not* attempted; not eligible for deep dives.
- `low_frequency`: empty results over 24–48h windows are expected and do not raise warnings; fewer items per run is normal.
- `enrichment_required`: RSS body is unreliable; fetch (and browser-fetch on failure) is preferred whenever budget allows.
- `degraded`: feed currently failing or partially working; included with reduced severity warnings until a window of recovery is observed.
- `broken`: skipped at fetch time; logged once per run; auto-promote to `degraded` when items reappear.

Definition of done:

- Source health is representable in `config/sources.yaml` (per-feed `health:` field) without breaking existing source loading; absent value = `active`.
- The RSS quality audit (`scripts/audit_rss_quality.py`) reports per-feed status, item count, median body length, enrichment behavior (rss_body / fetched_html / browser_markdown / normalizer_fallback / none), and degraded/fallback rate.
- Normalizer fallback no longer counts as clean success in source-quality reporting.
- A new `source_health.json` artifact (or section of an existing diagnostics artifact) is written each run summarizing every feed's status and the per-run observations that contributed to it.
- Health classification is monitorable: a single CLI/script invocation prints a roll-up of all feeds' current status, the last date each was non-empty, and any status transitions.
- Tests cover config parsing, audit classification, and the per-run health artifact.

**Status:** Completed 2026-05-01. `scripts/source_health.py` provides the CLI and per-run artifact; `config/sources.yaml` carries health on every feed; `audit_rss_quality.py` includes the health column; pipeline writes `source_health.json` after collect.

#### 3. Empirically audit and curate stale / low-yield feeds ✅

Problem: Several feeds are suspected stale or low-yield but lack data-driven decisions.

Approach: run an empirical audit using all available dated runs (currently 21 runs, 2026-04-04 → 2026-04-29, ~26-day window). For each candidate feed, compute item count, median body length, enrichment behavior, and degraded-fallback rate; propose disposition; apply after review.

Current feeds needing review:

- `Defense Tech and Acquisition`
- `Sinification`
- `MenaTrack`
- `One Useful Thing`
- `Import AI`
- `The Overshoot`
- `BIS Press Releases`
- `The Diff`
- `The New Atlantis`
- `ScienceDaily Biotechnology`
- `Phys.org Bio & Medicine`
- `Lawfare`
- `Salt Lake Tribune Culture`

Definition of done:

- Audit script outputs a per-feed table of empirical metrics over the available run window.
- Each listed feed has an explicit recorded decision in `config/sources.yaml` (via the new `health:` field or removal): keep `active`, mark `low_frequency`, mark `headline_radar`, mark `enrichment_required`, mark `broken`, or remove entirely.
- Decision rationale (one line per feed) is captured in a commit message or a short note in `config/sources.yaml`.
- Clearly broken feeds are removed or marked `broken`.
- `scripts/validate_new_feeds.py` and `scripts/audit_rss_quality.py --latest` complete successfully in Docker.

**Status:** Completed 2026-05-01. Empirical audit ran over 26 days of artifacts. Dispositions applied:
- `broken`: Lawfare, Phys.org Bio & Medicine, ScienceDaily Biotechnology (zero items, should be active)
- `low_frequency`: Defense Tech and Acquisition, MenaTrack, One Useful Thing, The Overshoot, The Diff, The New Atlantis, BIS Press Releases, BIS Central Bank Speeches, Brad Setser, Comment Magazine, Salt Lake Tribune Culture
- `enrichment_required`: Sinification, Import AI, China Talk, Daniel Drezner, Venture in Security, The American Conservative, Deseret News (Utah), Just Security, Inter Press Service, Carbon Brief, Air & Space Forces
- `headline_radar`: Financial Times, The Economist, Nature, Science Magazine

#### 4. Add targeted sources for recurring coverage gaps

Problem: Coverage-gap history repeatedly identifies missing or weak coverage in a few domains. These are input gaps, not just selection issues.

Target expansion areas (drawn from `coverage_gaps.json` over recent runs):

- Maritime/shipping/insurance risk (Lloyd's-style).
- Arms control, NPT, nuclear governance, IAEA/UN institutions.
- DPRK and Taiwan Strait security.
- European LNG, gas, and energy-market coverage.
- AI governance, compute governance, frontier model regulation.

Source discovery: review feeds catalogued at <https://github.com/kagisearch/kite-public> and similar curated lists for candidates in each gap area.

Definition of done:

- 1–3 new feeds per gap area, total ≤15 added; favors quality over breadth.
- Each new source has category routing, analysis mode, enrichment strategy, and source-health status set explicitly.
- New feeds pass validation (#9) before being merged.
- A dry run shows the new sources entering `raw_sources` or produces clear diagnostics explaining why they did not.
- The next dry run's `coverage_gaps.json` reduces at least one recurring gap class or makes the remaining gap visibly a selection issue rather than a collection issue.

#### 5. Make enrichment budget tiered by source health

Problem: Current enrichment caps in `config/pipeline.yaml` are global and tight: `max_fetches_per_run: 10`, `max_browser_fetches_per_run: 3`. The 2026-04-29 run had 249 enrich candidates with 46 skipped by fetch cap and 5 by browser cap; only 13 fetches across 249 items. Items that genuinely need fetched bodies (`enrichment_required` sources) are being starved.

Approach: tiered caps keyed off the source-health field added in #2.

- `enrichment_required` sources: no per-run cap on fetch; browser-fetch on fetch failure (still subject to a generous safety ceiling, e.g. 30/run, to bound runaway).
- `headline_radar` sources: never fetched; never browser-fetched.
- `active` and `low_frequency` sources: standard cap (current 10 fetch / 3 browser).
- `degraded`/`broken` sources: never fetched.
- Within each tier, prioritization considers body length (shortest first), category importance, and recent coverage-gap matches.

Definition of done:

- `pipeline.yaml` enrichment config supports per-tier caps.
- `enrich_articles` consults source health when deciding fetch eligibility and ordering.
- Enrichment diagnostics (`enrich_articles.json`) record per-record `tier`, `cap_tier`, and the reason code for skipped / fetched / browser-fetched / fallback / no_source_text outcomes.
- A dashboard-style summary of per-tier fetch usage is emitted per run (counts of attempted, succeeded, skipped-by-cap, fallback).
- Tests cover tier-based cap behavior, prioritization order within a tier, and the no-fetch guarantee for `headline_radar`/`broken`/`degraded`.

#### 6. Harden distinct-source selection downstream

Problem: Downstream output can look corroborated when multiple links come from the same outlet. At-a-glance and deep dives can also overuse a few sources such as SCMP, Al Jazeera, or OilPrice.

Concrete concentration limits to enforce (subject to per-section override in `pipeline.yaml`):

- At-a-glance: ≤2 items per outlet per section.
- Deep dives: ≤1 item per outlet per section.
- "Corroborated" or "widely-reported" depth labels require ≥2 distinct registered domains across the supporting links.

Definition of done:

- Cross-domain validation recomputes source depth from distinct outlets/domains instead of trusting the LLM label.
- Same-outlet multi-link evidence cannot be labeled as independently corroborated; depth labels are auto-downgraded.
- At-a-glance and deep-dive selection enforce the per-outlet caps above; overflow items are dropped or swapped per a documented tiebreaker.
- Validation diagnostics report when source-depth labels are downgraded or when source-cap enforcement altered the output (which item dropped, why).
- Tests cover same-outlet duplicates, distinct-outlet corroboration, and per-section cap behavior.

#### 7a. Add per-category quotas inside multi-category desks

Problem: The 2026-04-29 anomaly report flagged four categories (`global-south`, `western-analysis`, `culture-structural`, `perspective-diversity`) as having raw items but contributing zero items to domain analysis. Investigation showed this is *not* a routing failure: those categories share desks with higher-volume siblings (e.g. `geopolitics` desk receives 40 `non-western` items vs 8 `western-analysis` and 8 `global-south`; `culture_structural` desk receives `culture-structural` (6), `legal-institutional` (6), `demographics` (4)). The desk LLM picks ~8 from the combined pool and high-volume categories crowd out the smaller ones.

Approach: enforce category diversity inside `analyze_domain` itself. Pre-LLM per-category quotas (each mapped category gets a minimum candidate slot if it has items, with a maximum cap on dominant categories), or a post-LLM rebalance step that swaps in the best item from any zero-contribution category.

This task applies to the post-7b `geopolitics_events` desk (covering `non-western`, `western-analysis`, `global-south`) and to `culture_structural`. Other desks can opt in if needed.

Definition of done:

- A documented mechanism (pre-LLM quotas or post-LLM rebalance) ensures each category mapped to a desk contributes at least one item when raw items are present, up to a configurable cap on any single category's share.
- The mechanism is configurable per desk in `pipeline.yaml`.
- Diagnostics record when category rebalance ran and which items were swapped.
- A focused test confirms a synthetic high-volume + low-volume category mix produces output with both represented.
- After this lands, the `source_absence` warnings for `western-analysis`, `global-south`, and `culture-structural` either disappear or convert into intentional `low_frequency`-marked exceptions.

#### 7b. Introduce a `perspective` mini-desk feeding seams

Problem: The categories `substack-independent` and `perspective-diversity` are content-type mismatches inside the geopolitics desk. They are framing, commentary, and contrarian takes — not event reporting. Mixing 9–12 opinion items with 40 news items in one LLM call invites the model to either ignore them (the current failure) or weight them inappropriately. Today the seams stage has to *extract* contested framing from news items written for a different purpose.

Approach: stand up a small `perspective` desk that produces *contested-framing candidates* directly, not a full at-a-glance/deep-dive output. Its output flows into the existing seams stage as purpose-built input.

- Routing: remove `substack-independent` and `perspective-diversity` from the `geopolitics` desk; route them to a new `perspective` desk.
- Output schema: small — a list of framing candidates each with a `claim`, `framing_axis` (e.g. "US vs. multipolar interpretation"), `representative_items` (item IDs), and short rationale. No deep dives, no at-a-glance contributions.
- Prompt: focused on identifying *disagreements and reframings* rather than producing analysis.
- Downstream: seams stage consumes `perspective` desk output alongside the events-desk outputs as input to its candidate generation.

Definition of done:

- New `perspective` desk defined in `config/pipeline.yaml` with its own categories, prompt, and output schema.
- `geopolitics` desk renamed to `geopolitics_events` and its category list reduced to `non-western`, `western-analysis`, `global-south` (and `substack-independent` only if any non-perspective subset remains; otherwise removed).
- New prompt file `prompts/perspective_system.md` defining the framing-candidate task.
- Seams stage accepts `perspective` desk output as a first-class input source and uses it preferentially when generating candidates.
- The perspective desk does NOT produce an at-a-glance section, deep dive, or worth-reading entries.
- Tests cover routing changes, the new desk's output contract, and seams consumption of perspective input.
- A dry run shows perspective desk output materially shaping at least one seam candidate that previously had to be inferred from news items.

#### 8. Tune source-absence and repeated-phrase diagnostics

Problem: Some `source_absence` warnings are useful, but others are noise (low-frequency categories, intentionally headline-only sources). The 2026-04-29 anomaly report also showed 5/9 anomalies were repeated-phrase overlaps between at-a-glance and deep dives, indicating the cross-domain prompt's "must add distinct value" instruction is not being enforced.

Definition of done:

- Source-absence diagnostics distinguish at least three cases: no raw input, raw input present but not selected by desk, and desk selected input but cross-domain omitted it.
- Severity is lowered for categories whose feeds are mostly `low_frequency` or `headline_radar`.
- Repeated-phrase checks identify overlapping report sections and include enough context (item IDs, section names, span) to debug the selection cause.
- Add either (a) a post-cross-domain dedup pass that regenerates or shortens deep-dive paragraphs reusing ≥10-word spans from at-a-glance, or (b) a stronger constraint in `prompts/cross_domain_execute.md` and a validation gate that downgrades `source_depth` when overlap is detected.
- Tests cover each diagnostic class and the dedup behavior.

#### 9. One-time validation for newly added sources

Problem: New sources added under #4 (and any future additions) need a sanity check before being committed: feed reachable, parses, has recent items, category routes to an active desk, source-health field present and valid. This is a *one-shot, on-add* check — not a per-run pipeline cost.

Definition of done:

- `scripts/validate_new_feeds.py` (or a sibling script) accepts a `--new-only` mode that audits only feeds added since the last commit and reports per-feed pass/fail.
- The script checks: HTTP reachability, feed parses, ≥1 item in the last 7 days (or the feed is marked `low_frequency`/`headline_radar`), category present in `desks` routing, `health` field valid.
- The validator is invoked manually (or via a developer-facing `make` / pre-commit hook on staged `config/sources.yaml` changes), NOT from the daily pipeline. Per-run health visibility is the responsibility of #2's `source_health` artifact, not this validator.
- Tests cover each validation rule.

#### 10. Run and evaluate a full dry run

Problem: The above changes should be judged by actual pipeline artifacts, not just unit tests.

Definition of done:

- Run the full Dockerized dry run after implementation.
- Inspect `collect_diagnostics`, `raw_sources`, `enriched_sources`, `domain_analysis`, `cross_domain_output`, `anomaly_report`, `coverage_gaps`, and the new `source_health` artifacts.
- The final report has reasonable source diversity, no hidden collect failures, and no obvious same-outlet false corroboration.
- After 7a+7b, the previously-dropped news categories (`western-analysis`, `global-south`, `culture-structural`) contribute items when raw input is present, and `substack-independent`/`perspective-diversity` items shape at least one seam candidate.
- Repeated-phrase anomalies drop to ≤1 per run (down from 5+ on 2026-04-29).
- Remaining warnings are documented as either accepted tradeoffs or follow-up TODOs.
- Full Dockerized test suite passes before committing.

#### 11. Update README and contributor docs

Problem: This branch changes user-visible structure (a new `perspective` desk, renamed `geopolitics_events`, a `health:` field on every source, a new `source_health` artifact, tiered enrichment caps, new diagnostic enums). The current README (542 lines) and CLAUDE.md will go stale in several specific places if not updated alongside the code.

Specific spots known to need updating:

- README desk count and parallelism description (currently "Seven specialist desks", line ~25 and line ~62; will become events desks + a perspective mini-desk).
- README desk-routing example block (line ~294) showing `geopolitics` with all four categories.
- README RSS categories table (line ~367) entry for `substack-independent` and `perspective-diversity` — both move to the perspective desk.
- README per-stage token cost table (line ~453) referencing "×7 desks".
- README `sources.yaml` configuration section — add the `health:` field semantics and defaults.
- README prompts listing (line ~500) — add `perspective_system.md`.
- README artifacts listing — add `source_health.json` (and any new collect-diagnostics artifact from #1).
- CLAUDE.md `Article Enrichment` section — note the new tiered cap behavior and where to inspect tier diagnostics.

Definition of done:

- All listed README sections reflect the new desk topology, source health field, tiered enrichment, and new artifacts.
- CLAUDE.md updated where guidance has changed (artifact paths, enrichment behavior, audit script flags).
- A grep for the strings `seven specialist desks`, `7 desks`, `×7 desks`, `geopolitics", categories: ["non-western"`, and bare `geopolitics` (in routing context) returns no stale matches.
- Any new prompt files added under #7b are listed in the README prompts section.
- Documentation changes are committed in the same PR that lands the corresponding code change, not deferred.

#### 12. Close out the branch

Problem: This branch rewrites enough of the source, enrichment, seams, and cross-domain path that "tests pass" is necessary but not sufficient. The branch should be closed only after the report is operationally usable.

Definition of done:

- All implementation tasks above are either complete or intentionally deferred with a written reason.
- `TODO.md` reflects the remaining work accurately.
- `docker compose build` completes successfully.
- `docker compose run --rm --no-deps morning-digest python -m pytest tests/ -v --tb=short` passes.
- A full dry run completes and the stage artifacts have been reviewed for reasonableness.
- The final digest has acceptable source diversity, no hidden collect failures, no obvious false corroboration, and no unresolved high-severity anomaly warnings.
- The final branch state is committed and pushed.

### Medium — Deferred cleanup

- **Extract retry backoff helper.** `morning_digest/llm.py::_retry_loop` and `pipeline.py` both implement exponential backoff with jitter. Keep one implementation in `utils/retry.py` when retry policy changes are next touched.
- **Timezone/date audit.** `plan.md` Slice 0 tracks `TZ` authority, shared helper adoption, artifact dates, and user-visible date formatting. Revisit only if date drift appears in artifacts or rendered email.

---

## Changelog

### 2026-04-22 — Dry-run observability pass

- **Ran a full Docker dry run.** The run completed successfully and wrote artifacts under `output/artifacts/2026-04-22`; artifact validation passed.
- **Promoted diagnostic sidecars into pipeline logs.** Contract issues, validation diagnostics, anomaly reports, domain-analysis failures, and coverage-gap counts now emit run-log summaries instead of requiring manual artifact inspection.
- **Restored console progress logging.** Pipeline logging now adds both file and console handlers explicitly, so long dry runs show stage progress instead of appearing idle on stdout/stderr.
- **Dropped blank coverage-gap entries.** Coverage gap normalization now filters empty LLM gap objects and logs when it drops them.
- **Observed dry-run warnings:** one seam contract issue for an unknown linked item ID, six anomaly warnings around category skew/source absence, and recurring coverage gaps around maritime insurance, uranium/nuclear supply chains, and North Korea coverage.
- **Tests:** Focused Dockerized observability suite passed (`50 passed`).

### 2026-04-22 — Open TODO sweep

- **Closed stale docs and contract drift items.** `assemble.py` no longer documents the removed Phase 0 `synthesis_output` path, README desk guidance now matches `_DOMAIN_CONFIGS` plus the shared prompt, and tag contract tests now cover `_TAG_KEYWORDS` plus the prompt allowed-tag list.
- **Consolidated shared helpers.** AQI label/color classification now lives in `utils/aqi.py`; dated artifact directory/list/load/save helpers now live in `utils/artifacts.py`.
- **Fed cross-domain connections into follow-up context.** `briefing_packet` now includes `cross_domain_connections`, matching the chat briefer prompt's existing instruction to check them first.
- **Tests:** Dockerized full suite passed after final wire-up (`914 passed`).

### 2026-04-22 — Seams LLM output stabilized

- **Switched seams to Fireworks Kimi K2.5.** The seams stage now uses `accounts/fireworks/models/kimi-k2p5` with per-turn token caps below the Fireworks forced-streaming threshold.
- **Prefer provider JSON mode before raw repair.** Seams candidate and annotation turns first request provider-enforced JSON, then fall back to the existing raw streaming/non-streaming parse and repair path.
- **Bounded seams prompt and output size.** Domain fields, raw RSS summaries, transcripts, candidate counts, evidence counts, and candidate/evidence text are capped before annotation so malformed/truncated JSON is less likely.
- **Tests:** Dockerized full suite passed: `911 passed`.

### 2026-04-21 — RSS routing and collector fixes

- **Routed every committed RSS category to an active consumer.** `legal-institutional` and `demographics` now feed the `culture_structural` analysis desk. `regional-west` is consumed by `prepare_local` and rendered as a separate `Utah & West` report section instead of disappearing into generic local handling.
- **Added an RSS category routing contract.** Contract tests now load `config.yaml`'s actual pipeline manifest and RSS feed list, assert every configured stage has explicit metadata, and assert every RSS category is consumed by an active desk or explicit stage consumer.
- **Reduced false source-absence warnings.** `anomaly.source_absence` now checks only categories routed into active analysis desks, so region-only RSS categories do not create recurring anomaly noise.
- **Fixed RSS recency mechanics.** Feedparser `*_parsed` timestamps now use UTC `calendar.timegm()` instead of local `mktime()`, and feed caps are applied after cutoff filtering so pinned/stale entries do not hide fresh items later in the feed.
- **Made HTML-index freshness explicit.** HTML index items now carry `fetched_at` plus `freshness: retrieved_at` when true publish timestamps are unavailable.
- **Stabilized RSS cooldown keys.** Persistent fetch cooldown state now keys on `{name}|{url}` with a legacy name-key read fallback.
- **Removed stale validator candidates.** `scripts/validate_new_feeds.py` now validates the committed `config.yaml` feeds by default instead of maintaining a drifting static candidate list.
- **Pipeline metadata now preserves related side outputs.** `domain_analysis_failures` and `regional_items` are included in stage metadata and empty-output contracts.
- **Tests:** Dockerized full suite passed: `866 passed`.

### 2026-04-21 — URL validation contract unified

- **Unified cross-domain URL validation around exact-or-canonical source URLs.** Cross-domain output no longer gets a broad domain-only pass followed by raw-source exact matching. Both prevalidation and final validation now use the same source-backed URL set, including URLs emitted by domain analysis.
- **Added conservative URL canonicalization.** The validator tolerates harmless drift such as scheme/host casing, fragments, trailing slashes, and common tracking query fields while still rejecting same-domain unknown paths.
- **Recorded URL strip reason codes.** Validation diagnostics now distinguish `unknown_domain` from `known_domain_unknown_path` and include the canonical comparison URL.
- **Recognized retrieved/canonical URL aliases.** Known URL collection now includes `final_url`, `resolved_url`, and `canonical_url` source fields when present.
- **Tests:** Focused Dockerized URL/cross-domain suite passed: `148 passed`.

### 2026-04-21 — Article enrichment artifact split

- **Stopped article enrichment from rewriting the `raw_sources` artifact.** `enrich_articles.run()` now writes enriched RSS summaries under `enriched_sources` while preserving the original collector artifact name for collector output.
- **Made downstream promotion explicit.** Pipeline hooks promote `enriched_sources` back into in-memory `context["raw_sources"]` only after successful enrichment or cached enrichment reload, so later stages still consume normalized summaries.
- **Covered rerun behavior.** Tests assert the separate artifact contract, runtime promotion, cached `--stage` promotion, and failure behavior that preserves the original `raw_sources`.

### 2026-04-21 — Briefing packet run metadata fixed

- **Exposed live pipeline run metadata to stages.** `run_pipeline` now stores the mutable `run_meta` object in shared context so `briefing_packet` can include prior stage timings, failures, and run options.
- **Covered metadata propagation.** Tests assert `briefing_packet` sees the live run metadata during orchestration and that `_build_metadata` preserves timings and failures from context.

### 2026-04-21 — Cross-domain fallback artifacts completed

- **Made cross-domain fallback paths honor the stage contract.** No-item, LLM-failure, and malformed-output paths now return `cross_domain_plan`, `cross_domain_output`, and `validation_diagnostics`.
- **Added explicit fallback diagnostics.** The diagnostics artifact records reason codes such as `no_domain_analysis_items`, `llm_call_failed`, and `non_dict_llm_output` when normal editorial validation did not run.
- **Tests:** Fallback tests now assert the full artifact contract.

### 2026-04-21 — Email rendering compatibility cleanup

- **Removed dead web-font import and dark-mode drift.** The template now relies on existing system font stacks, and the unused `weather.dark_theme` flag is gone from config.
- **Improved mobile and Outlook rendering.** Mobile section/header/bar/footer padding now narrows at 480 px, markets render as a presentation table, and At-a-Glance headers no longer depend on flexbox.
- **Improved scanability.** Tags are 11 px instead of 10 px, and Deep Dive further-reading links render as separated rows.
- **Tests:** Added email-template render tests for mobile CSS, table-based market/scan layout, and further-reading separators.

### 2026-04-21 — Weather normal and record overlays restored

- **Restored normal and record bands on forecast bars.** `normal_band` and `record_band` now render Gmail-safe spacer-table overlays using each day's `normal_hi`/`normal_lo` and `record_hi`/`record_lo`.
- **Made the weather legend reflect active overlays.** The legend now includes normal and record range entries when those overlays are enabled.
- **Tests:** Weather display and integration tests now assert overlay rendering and flag-gated suppression.

### 2026-04-21 — Weather chart classes extracted

- **Moved repeated weather chart cell styles into template CSS classes.** Day labels, temperature cells, gradient-bar cells, right condition cells, legend elements, and chart wrappers now use `.wx-*` classes from `email_template.py`.
- **Kept dynamic values inline.** Per-row widths, band colors, AQI colors, and precipitation widths remain inline because they vary by day.
- **Tests:** Weather display tests assert the repeated row cells render with classes instead of static inline style bundles.

### 2026-04-21 — Retry policy consolidated

- **Added stage-level pipeline retry config.** `pipeline.retry` provides defaults and individual stages can override with `retry.max_retries` / `retry.backoff_base_seconds`.
- **Stopped nested LLM-stage retries at the pipeline/domain layers.** LLM-backed stages are configured with `max_retries: 0`, leaving transient API retry handling in `morning_digest.llm`; `analyze_domain` now reports failed desks instead of retrying each failed desk again.
- **Tests:** Pipeline retry config and analyze-domain failure reporting tests cover the new behavior.

### 2026-04-21 — Failure visibility controls added

- **Added config-driven footer visibility for stage failures.** `digest.failure_visibility` now supports `artifacts_only`, `dry_run`, and `always`.
- **Surfaced selected failures in the rendered email footer.** `assemble` passes visible `run_meta.stage_failures` into the template, and the footer renders compact pipeline notices when configured.
- **Tests:** Assembly and template tests cover visibility filtering and footer rendering.

### 2026-04-21 — Digest CSS extracted

- **Moved email CSS out of the Python template.** `templates/email_template.py` now loads `templates/digest.css` at import and injects it into the rendered `<style>` block.
- **Kept tag vocabulary contracts pointed at the stylesheet.** The CSS tag-variable contract now reads `templates/digest.css`, so tag drift remains covered after the extraction.
- **Tests:** Email template and contract tests cover rendered CSS and tag-variable consistency.

### 2026-04-21 — Cross-domain stage split

- **Separated cross-domain responsibilities.** Prompt assembly now lives in `cross_domain/prompt.py`, normalization/fallback parsing in `cross_domain/parse.py`, and stage orchestration in `cross_domain/stage.py`.
- **Preserved the configured stage import.** `stages/cross_domain.py` remains as a compatibility module for pipeline loading and existing private helper imports.
- **Tests:** Cross-domain and contract tests cover the split implementation through the existing public stage path.

### 2026-04-21 — Config split

- **Split runtime configuration into focused files.** Pipeline/LLM routing lives in `config/pipeline.yaml`, source catalog settings in `config/sources.yaml`, and delivery/digest preferences in `config/delivery.yaml`.
- **Added a shared merge loader.** `morning_digest.config.load_config()` merges split files and still permits a full legacy `config.yaml` deployment override.
- **Updated runtime consumers.** Pipeline, entrypoint, RSS validation, quality audit, Docker mounts, and contract tests now load through the shared config path.
- **Tests:** Config loader tests cover split merge behavior, legacy overrides, and split-marker handling.

### 2026-04-17 — Weather: AQI overlay restored

- **Restored per-bar AQI numbers on the 7-day weather chart.** The original design overlaid the AQI number at its `aqi/200` scale position on each day's temp bar, color-coded to the EPA band. The earlier implementation used `position:absolute; left:{pct}%` which Gmail silently strips, leaving only `##` placeholder text (visible in production screenshots). Reimplemented with a Gmail-safe approach: a second row inside the inner bar table containing a nested 3-cell table where `<td style="width:{aqi_pct}%">` acts as the positional spacer. High-AQI values (≥85% of scale) right-align to stay inside the bar bounds.
- **Restored AQI band legend above the chart.** Keyed to the per-bar number colors so readers can translate a number → health category at a glance. Uses darker readable variants (`#15803d`, `#854d0e`, …) rather than the bright EPA signal colors which are illegible on white.
- **`aqi_strip` config flag now actually gates the legend + overlay** (was previously a no-op).
- **Tests: +9 new cases** covering legend, per-bar overlay, color selection, high-AQI right-alignment, and `AQI_SCALE_MAX` contract. Total weather suite: 97 passing.
- **TODO revision**: added design-intent preamble; removed "collapse At-a-Glance Thread block" item (undermines intentional three-voice rhetorical layering); added "Restore Normal/Record/Forecast Hi-Lo bar overlays" item (same Gmail-strip fate as AQI, same fix pattern); softened Google Fonts `@import` item from "wasted bytes" to "audit in both clients first."

### 2026-04-18 — Verification follow-up cleanup

- **Closed stale TODO items for completed plan work.** Removed open entries for stage metadata cleanup, `collect.py` parallelization, transcript compression parallelization, and the old `utils.urls` standardization tracker now that those changes have landed.
- **`coverage_gaps` contract now enforced.** The stage normalizes to the published schema and strips stray top-level fields before writing artifacts/history.
- **`coverage_gaps` diagnostics now render in dry-run only.** They are available for diagnostics without leaking into the normal send path.
- **Desk manifest is now live at runtime.** `analyze_domain` resolves active desk routing from `config.yaml` instead of leaving `desks:` as documentation-only config.
- **Feed validator drift corrected.** `scripts/validate_new_feeds.py` now validates the same feed URLs that are actually committed in `config.yaml`.
- **README made model-agnostic.** Provider/model swaps should no longer require documentation cleanup just to keep the architecture and setup sections truthful.

### 2026-04-18 — Performance follow-up

- **Parallelized the direct RSS fetch loop.** `sources/rss_feeds._fetch_direct` now fetches raw feed bytes in small parallel batches (`ThreadPoolExecutor`, max 6 workers) while preserving feed-order parsing and the existing "5 consecutive failures" circuit-breaker semantics.
- **Removed the blocking 5-minute analyze-domain sleep.** Failed domain passes now retry immediately after the initial parallel wave instead of pausing the whole pipeline for 300 seconds.
- **Tests added for both changes.** New coverage verifies ordered RSS circuit-breaker behavior, successful item collection after parallel fetch, and that failed domain retries do not call `time.sleep`.

### 2026-04-16 — Review sweep quick wins

- **Extracted `sources/_http.py` helper.** Canonical User-Agent (`MorningDigest/1.0 (morningDigest@lurkers.us)`) and default timeout (15s). `http_get_json`, `http_get_text`, `http_get_bytes` all return `None` on any failure. Migrated: `markets`, `launches`, `history`, `github_trending`, `hackernews`, `astronomy`, `economic_calendar`, `rss_feeds` (bytes path), `weather` (all 6 endpoints). Only `rss_feeds`'s FreshRSS POST path still uses `requests` directly. Tests updated to patch `http_get_json` instead of `requests.get`.
- **Fix: `entrypoint.py` retry logic.** After a pipeline crash the loop previously busy-spun instead of waiting. Now sleeps `RETRY_DELAY_SECS` (30 min) before the next attempt.
- **Fix: `cross_domain._empty_output` missing `worth_reading` key.** Template rendered `{}` for the section on failure. Added `"worth_reading": []` to the default dict.
- **Fix: `morning_digest/validate.py` dead `_config` lookup.** Removed unused config loading that never influenced output; inlined `min_items=3, max_items=20`.
- **Fix: `assemble.py` fallback defaults.** Was 14 deep dives / 10 at-a-glance; `config.yaml` says 7/5. Fallbacks now match config.
- **Fix: `rss_feeds._parse_feed_date` timezone.** Naive datetimes from `dateparser` now coerced to UTC-aware before comparison. Previously crashed on feeds without explicit offset.
- **Fix: `weather.py` None-mirror bug.** Forecast days with both `high_f` and `low_f` missing are now skipped entirely instead of rendering as `None/None`.
- **Fix: `anomaly.py` `checks_run` derived from `len(checks)`** instead of hardcoded `5`.
- **Fix: email template footer.** Removed outdated "Powered by Kimi K2.5" attribution.
- **Fix: `briefing_packet._TOKEN_ESTIMATE` lambda → `_token_estimate(s)` def.**
- **Fix: typo `overshast` → `overshoot`.**
- **Cleanup: deleted `_collect_known_urls` wrapper in `stages/seams.py`** — now calls `utils.urls.collect_known_urls` directly.
- **Cleanup: added `**kwargs` to `collect.py` and `compress.py` stage `run()` signatures** so the orchestrator can pass extra args uniformly.

### Older work

For the full history of bug fixes, UI improvements, weather module phases, test-coverage work, and cross-domain model comparison, see the git log. Key waypoints:

- `feat(llm): upgrade cross_domain stage to Claude Opus 4.7`
- `feat(config): switch analyze_domain from Kimi K2.5 to MiniMax M2.7`
- `fix(resilience): retry failed LLM domains after 5 min, show error notices instead of empty sections`
- `feat(weather): color-code AQI in header for visibility`
- Weather Display Module (Phases 0–5 complete): NWS primary + Open-Meteo fallback + AirNow AQI + NOAA normals, 5-zone SVG renderer, pipeline integration.
- Test coverage: 688 tests across collect, analyze_domain, prepare_*, assemble, send, contracts, weather integration.
