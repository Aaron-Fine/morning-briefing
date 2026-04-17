# Morning Digest — TODO

_Last updated: 2026-04-17_

---

## Open

### High — Design (HTML / email)

- **Weather bar inline-style soup.** Stale-legend cleanup landed 2026-04-17, but the chart is still emitted as one long line of inline `style=""` attributes per day row — hard to scan, hard to tune, inflates the email payload. Promote the repeating styles (day-name cell, temp cell, gradient-bar cell, right column) to classes in `templates/email_template.py`'s `<style>` block; keep only per-row dynamic values (widths, colors, text) inline.
- **Dark mode configured but not implemented.** `config.yaml:120` sets `dark_theme: true` but the palette is fixed light. Add a `@media (prefers-color-scheme: dark)` block in the template that overrides the `:root` custom properties — Proton/Gmail on dark devices currently render the light palette.
- **Mobile padding too tight.** `.section { padding: 24px 32px }` leaves ~310 px of usable width on a 375 px phone. Add `@media (max-width: 480px)` halving horizontal padding to 16 px.
- **Google Fonts import is wasted bytes.** `email_template.py:23` loads JetBrains Mono + DM Sans; Gmail/Proton strip `@import` in email HTML and the template already falls back to `Courier New` / `-apple-system`. Drop the `@import` and the font names it references.
- **Flexbox in `.markets` and `.scan-header` breaks in Outlook.** Fall back to a table-based layout for the market strip.
- **At-a-Glance context blocks are visually heavy.** Three nested blocks (Sources / Analysis / Thread) × 7 items = a lot of scrolling. Consider collapsing `Thread` to a single italic line, or making `Analysis` the default and `Sources` a smaller "cited:" footer.
- **Deep Dive `Further Reading` links have no visual separation** (`email_template.py:334`). Each anchor is block-level; add bullet separators or spacing.
- **10 px uppercase tags** at the edge of legibility. Bump to 11 px.

### High — Design (architecture)

- **Stage-specific branches in `pipeline.py`.** `pipeline.py:301` (cross_domain loads prev-day), `:316` (cross_domain gets `force_friday`), `:361` (assemble writes HTML files) — orchestrator keeps growing per-stage special cases. Give stages a standard lifecycle (`pre_run(context, run_meta)` + `post_run(outputs, artifact_dir)` hooks) and move these into `stages/cross_domain.py` and `stages/assemble.py`.
- **Central registries should be per-stage metadata.** `_stage_artifact_key` (`pipeline.py:401`), `_empty_stage_output` (`:421`), `_NON_CRITICAL_STAGES` (`:41`) all force pipeline.py edits when adding a stage. Let each `stages/<name>.py` export `ARTIFACT_KEY`, `EMPTY_OUTPUT`, `CRITICAL`; read those from the orchestrator.
- **Retry policy is global.** `max_retries=2` + fixed backoff in `_run_with_retry` (`pipeline.py:165`). LLM stages and scraper stages want different budgets. Put retry config per stage in `config.yaml`.
- **`config.yaml` is doing four jobs** (pipeline manifest, LLM routing, source catalog, delivery prefs). 246 lines. Split into `config/pipeline.yaml`, `config/sources.yaml`, `config/delivery.yaml` and merge at load.
- **Stage I/O is untyped dicts.** `context.get("domain_analysis", {})` everywhere. Pydantic models for `DomainAnalysis`, `CrossDomainOutput`, `SeamData` would catch schema drift — that seam is the most likely silent-regression spot.
- **`email_template.py` is 400+ lines of CSS-in-a-Python-string.** Extract to `templates/digest.css` and load at import so it can be linted and diffed cleanly.
- **Failure visibility.** `run_meta["stage_failures"]` is saved to an artifact but never surfaced to the reader. Render a compact "Pipeline notes" strip in the email footer when any non-critical stage failed.
- **`stages/cross_domain.py` at 525 lines** likely mixes prompt construction, LLM call, and response parsing. Split into `cross_domain/prompt.py`, `cross_domain/parse.py`, `cross_domain/stage.py`.

### High — Performance

- **Parallelize `analyze_domain` domain passes.** `stages/analyze_domain.py` calls LLM once per domain (ai_tech, geopolitics, econ-trade, defense-space) sequentially. Four independent LLM calls run ~4× slower than they should. Move to `concurrent.futures.ThreadPoolExecutor` keyed on domain name. Keep `_failed` flag handling per-pass so one failure doesn't poison the others.
- **Parallelize `collect.py` sources.** `stages/collect.py` fetches RSS, HN, GitHub trending, launches, astronomy, markets, econ calendar, holidays, CFM, history, YouTube transcripts serially. Most are independent HTTP calls. A `ThreadPoolExecutor` with ~6 workers would cut wall time substantially. Be careful to preserve deterministic ordering in outputs.
- **Parallelize RSS fetch loop.** `sources/rss_feeds._fetch_direct` pulls feeds one-at-a-time. With ~30 feeds at ~1s each this is the biggest single contributor to collect latency. Move to `ThreadPoolExecutor`. Preserve the "5 consecutive failures → network down → abort" circuit breaker by tracking failures atomically.
- **Parallelize transcript compression.** `stages/compress.py` runs the transcript compression LLM call once per transcript. These are independent; parallelize them.
- **Remove uncoordinated 3-layer retry stack.** Retries exist at the pipeline level (30-min retry in `entrypoint.py`), the LLM helper (`llm._retry_loop`, ~3 attempts with backoff), and per-domain (`analyze_domain` retries the whole domain after 5 min). Worst case: a single flaky call produces `3 × 2 × N` attempts before giving up. Consolidate: LLM helper retries transient 5xx only, domain/pipeline treat a failed LLM call as "done, failed", no nested retry.
- **Remove `time.sleep(300)` in `analyze_domain`.** The 5-min sleep-and-retry for failed domains blocks the pipeline. Either (a) drop it in favor of the pipeline-level 30-min retry, or (b) do the retry asynchronously so other domains continue.

### Medium — Consolidation

- **Consolidate `_TAG_LABELS`.** Defined in `cross_domain.py`, `assemble.py`, and `validate.py` (as `VALID_TAG_LABELS`). Contract tests catch drift but the duplication itself is the bug. Move to `utils/tags.py` and import everywhere.
- **Consolidate AQI breakpoint ladder.** The `if aqi <= 50: "Good" / <= 100: "Moderate" / ...` ladder appears in `sources/weather.py::_aqi_to_label` and twice more in `modules/weather_display.py` (label + color). Extract to `utils/aqi.py` with `aqi_label(aqi)` and `aqi_color(aqi)`.
- **Extract retry backoff helper.** `llm.py::_retry_loop` and `pipeline.py` both implement exponential backoff with jitter. Once the 3-layer retry stack is consolidated (see above), keep one implementation in `utils/retry.py`.
- **Extract artifact helpers.** `_ARTIFACTS_BASE` path + date-directory iteration is duplicated in `pipeline.py` and `stages/anomaly.py`. Move to `utils/artifacts.py` (`artifact_dir(date)`, `iter_recent_dirs(n)`, `load_artifact(date, key)`).
- **Audit `utils.urls` usage.** `collect_known_urls`, `normalize_url`, and URL-equality logic are used in `cross_domain`, `analyze_domain`, `anomaly`, `briefing_packet`. Some still use raw `urlparse().netloc` comparison. Standardize on the `utils.urls` helpers everywhere.

### Low — Correctness / cleanup

- **Naive `datetime.now()` mixed with tz-aware.** ~10 locations use `datetime.now()` without a tz, then compare against tz-aware datetimes elsewhere. Audit and standardize on `datetime.now(timezone.utc)`. Ruff rule DTZ005 would catch these automatically if enabled.
- **Phase 0 dead code in `assemble.py`.** The "empty fallback" branch is only reachable when Phase 3 (`cross_domain`) produces nothing, which hasn't happened since the `_failed` flag landed. Verify unreachable and delete, or keep but document the invariant.
- **`test_analyze_domain` `_empty_domain_result` drift.** Tests assert `{"items": []}` but the function now returns `{"items": [], "_failed": False}` (from the resilience fix). Update the assertions to match current contract.

---

## Changelog

### 2026-04-16 — Review sweep quick wins

- **Extracted `sources/_http.py` helper.** Canonical User-Agent (`MorningDigest/1.0 (morningDigest@lurkers.us)`) and default timeout (15s). `http_get_json`, `http_get_text`, `http_get_bytes` all return `None` on any failure. Migrated: `markets`, `launches`, `history`, `github_trending`, `hackernews`, `astronomy`, `economic_calendar`, `rss_feeds` (bytes path), `weather` (all 6 endpoints). Only `rss_feeds`'s FreshRSS POST path still uses `requests` directly. Tests updated to patch `http_get_json` instead of `requests.get`.
- **Fix: `entrypoint.py` retry logic.** After a pipeline crash the loop previously busy-spun instead of waiting. Now sleeps `RETRY_DELAY_SECS` (30 min) before the next attempt.
- **Fix: `cross_domain._empty_output` missing `worth_reading` key.** Template rendered `{}` for the section on failure. Added `"worth_reading": []` to the default dict.
- **Fix: `validate.py` dead `_config` lookup.** Removed unused config loading that never influenced output; inlined `min_items=3, max_items=20`.
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
