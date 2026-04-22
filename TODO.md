# Morning Digest — TODO

Last updated: 2026-04-21

> **Design-intent note.** When triaging items marked "stale" or "unused,"
> first ask whether the feature was *intentional but silently broken* (e.g.
> Gmail stripping positioning). If so, restore — don't delete. The AQI
> overlay (restored 2026-04-17) is a canonical example.

---

## Open

### High — Review sweep (2026-04-21)

### Low — Review sweep (2026-04-21)

- **Documentation still references dead or misleading architecture.** `stages/assemble.py` advertises a Phase 0 `synthesis_output` mode in its docstring but the implementation no longer has a `synthesis_output` branch. README says adding a desk means creating `prompts/desk_<name>.md`, while current desks are hard-coded in `_DOMAIN_CONFIGS` and use one shared prompt. This is the kind of stale doc that makes the next change worse than it needs to be.
- **Tag contract tests miss half the promised contract.** AGENTS says tag vocabulary is synchronized across five surfaces, including `_TAG_KEYWORDS` and the prompt tag list. `tests/test_contracts.py` checks labels/CSS and merely checks field names in `_SYSTEM_PROMPT`; it does not parse the allowed tag list in `prompts/cross_domain_execute.md`, and it does not assert keyword coverage for new tags. Add tests that fail when a tag is added without prompt and keyword updates.
- **`cross_domain_connections` are generated and then mostly thrown in a drawer.** `assemble` saves them only in `digest_json["cross_domain_connections"]`; the email does not render them, and anomaly checks do not inspect them. Either render a compact section, feed them into seam annotations, or stop spending output tokens on them.
  - Decision: keep them. Cross-domain connections are a key analytical input that the final report generator should draw on.

### High — Design (architecture)

- **`config.yaml` is doing four jobs** (pipeline manifest, LLM routing, source catalog, delivery prefs). 246 lines. Split into `config/pipeline.yaml`, `config/sources.yaml`, `config/delivery.yaml` and merge at load.
- **Stage I/O is untyped dicts.** `context.get("domain_analysis", {})` everywhere. Pydantic models for `DomainAnalysis`, `CrossDomainOutput`, `SeamData` would catch schema drift — that seam is the most likely silent-regression spot.

### High — Performance

- ~~**Tracked in `plan.md` Slice 10: parallelize `analyze_domain`.**~~ Done — 7 desk passes run via ThreadPoolExecutor (max 4 workers) with per-desk failure isolation.

### Medium — Consolidation

- ~~**Tracked in `plan.md` Slice 6: consolidate tag vocabulary helpers.**~~ Done — `energy` and `biotech` tags added to all 5 synchronized surfaces (validate, cross_domain, assemble, CSS, TAG_KEYWORDS). Contract tests verify consistency.
- **Consolidate AQI breakpoint ladder.** The `if aqi <= 50: "Good" / <= 100: "Moderate" / ...` ladder appears in `sources/weather.py::_aqi_to_label` and twice more in `modules/weather_display.py` (label + color). Extract to `utils/aqi.py` with `aqi_label(aqi)` and `aqi_color(aqi)`.
- **Extract retry backoff helper.** `morning_digest/llm.py::_retry_loop` and `pipeline.py` both implement exponential backoff with jitter. Once the 3-layer retry stack is consolidated (see above), keep one implementation in `utils/retry.py`.
- **Extract artifact helpers.** `_ARTIFACTS_BASE` path + date-directory iteration is duplicated in `pipeline.py` and `stages/anomaly.py`. Move to `utils/artifacts.py` (`artifact_dir(date)`, `iter_recent_dirs(n)`, `load_artifact(date, key)`).
- **Investigate recurring dry-run source warnings.** Current end-to-end dry-runs complete successfully, but `output/digest.log` consistently shows non-fatal source issues for SpaceNews (`429`), Brad Setser (`404`), Reuters Markets (`401`), China Global South Project (`410`), and The Diff (`400`). Decide case by case whether to:
  - fix the feed URL,
  - add provider-specific throttling/backoff,
  - replace the source,
  - or downgrade/remove the source if it is no longer viable.

### Low — Correctness / cleanup

- **Tracked in `plan.md` Slice 0: timezone/date audit.** The current plan now covers `TZ` authority, shared helper adoption, artifact dates, and user-visible date formatting across the codebase.
- **Phase 0 dead code in `assemble.py`.** The "empty fallback" branch is only reachable when Phase 3 (`cross_domain`) produces nothing, which hasn't happened since the `_failed` flag landed. Verify unreachable and delete, or keep but document the invariant.
- **Tracked in `plan.md` Slice 0: `_empty_domain_result` contract drift.** Keep follow-up notes here only if additional edge cases appear during implementation.

---

## Changelog

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
