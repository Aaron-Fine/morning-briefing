# Morning Digest — TODO

Last updated: 2026-04-18

> **Design-intent note.** When triaging items marked "stale" or "unused,"
> first ask whether the feature was *intentional but silently broken* (e.g.
> Gmail stripping positioning). If so, restore — don't delete. The AQI
> overlay (restored 2026-04-17) is a canonical example.

---

## Open

### High — Design (HTML / email)

- **Weather bar inline-style soup.** Chart is emitted as one long line of inline `style=""` attributes per day row — hard to scan, hard to tune, inflates the email payload. Promote the repeating styles (day-name cell, temp cell, gradient-bar cell, right column) to classes in `templates/email_template.py`'s `<style>` block; keep only per-row dynamic values (widths, colors, text) inline.
- **Restore Normal / Record / Forecast Hi-Lo bar overlays.** `sources/weather.py::_compute_normals_and_records` still collects `normal_hi`, `normal_lo`, `record_hi`, `record_lo` per day and exposes the `normals` array; `config.yaml` has `record_band: true` and `normal_band: true`. These were meant to gate band overlays on each day's temp bar — the original positioning relied on `position:absolute` which Gmail strips, so they silently disappeared (same fate as AQI before the 2026-04-17 restoration). Restore using the same approach as `_build_chart_html`'s AQI row (spacer-cell width inside a nested table), gated by the `record_band`/`normal_band` flags. Until restored, those flags are no-ops — see `test_band_flags_accepted`.
- **Dark mode configured but not implemented.** `config.yaml:120` sets `dark_theme: true` but the palette is fixed light. Add a `@media (prefers-color-scheme: dark)` block in the template that overrides the `:root` custom properties — Proton/Gmail on dark devices currently render the light palette.
- **Mobile padding too tight.** `.section { padding: 24px 32px }` leaves ~310 px of usable width on a 375 px phone. Add `@media (max-width: 480px)` halving horizontal padding to 16 px.
- **Audit Google Fonts `@import`.** `email_template.py:23` loads JetBrains Mono + DM Sans. Gmail strips `@import` in email HTML; Proton behavior varies by client. Verify in both clients whether the imported fonts ever actually resolve; if they never do, drop the `@import` (system-font fallbacks already specified). If they do in some clients, document *which* so the tradeoff is visible.
- **Flexbox in `.markets` and `.scan-header` breaks in Outlook.** Fall back to a table-based layout for the market strip.
- **Deep Dive `Further Reading` links have no visual separation** (`email_template.py:334`). Each anchor is block-level; add bullet separators or spacing.
- **10 px uppercase tags** at the edge of legibility. Bump to 11 px.

### High — Design (architecture)

- **Retry policy is global.** `max_retries=2` + fixed backoff in `_run_with_retry` (`pipeline.py:165`). LLM stages and scraper stages want different budgets. Put retry config per stage in `config.yaml`.
- **`config.yaml` is doing four jobs** (pipeline manifest, LLM routing, source catalog, delivery prefs). 246 lines. Split into `config/pipeline.yaml`, `config/sources.yaml`, `config/delivery.yaml` and merge at load.
- **Stage I/O is untyped dicts.** `context.get("domain_analysis", {})` everywhere. Pydantic models for `DomainAnalysis`, `CrossDomainOutput`, `SeamData` would catch schema drift — that seam is the most likely silent-regression spot.
- **`email_template.py` is 400+ lines of CSS-in-a-Python-string.** Extract to `templates/digest.css` and load at import so it can be linted and diffed cleanly.
- **Failure visibility.** `run_meta["stage_failures"]` is saved to an artifact but never surfaced to the reader. Render a compact "Pipeline notes" strip in the email footer when any non-critical stage failed.
- **`stages/cross_domain.py` at 525 lines** likely mixes prompt construction, LLM call, and response parsing. Split into `cross_domain/prompt.py`, `cross_domain/parse.py`, `cross_domain/stage.py`.

### High — Performance

- ~~**Tracked in `plan.md` Slice 10: parallelize `analyze_domain`.**~~ Done — 7 desk passes run via ThreadPoolExecutor (max 4 workers) with per-desk failure isolation.
- **Remove uncoordinated 3-layer retry stack.** Retries exist at the pipeline level (30-min retry in `entrypoint.py`), the LLM helper (`llm._retry_loop`, ~3 attempts with backoff), and per-domain (`analyze_domain` retries the whole domain after 5 min). Worst case: a single flaky call produces `3 × 2 × N` attempts before giving up. Consolidate: LLM helper retries transient 5xx only, domain/pipeline treat a failed LLM call as "done, failed", no nested retry.

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
