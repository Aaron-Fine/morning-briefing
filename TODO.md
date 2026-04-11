# Morning Digest — TODO

_Last updated: 2026-04-10_

---

## Done

### Bug fixes
- **`--force-friday` was broken** — only passed to `synthesize` (dead stage). Fixed: now passed to `cross_domain` in `pipeline.py`; `cross_domain.py` updated to accept `force_friday` kwarg and pass it to `_build_input`.
- **Press release filter** — `stages/prepare_local.py` now filters items with `/press_releases/` in URL or PRNewswire/BusinessWire markers in summary.
  - **Bonus bug found and fixed**: `PRNewswire` (without slashes) wasn't caught in summaries. Changed `/PRNewswire/` → `PRNewswire` in `_WIRE_MARKERS`.
- **`prepare_calendar.py` launch data keys wrong** — used `launch.get("net")` and `launch.get("mission")` but `sources/launches.py` returns `"date"` and `"mission_description"`. Fixed: keys now match.
- **NWS forecast high/low parsing** — `sources/weather.py:269` used `existing.get("is_daytime")` (always the first period's value) instead of `p.get("isDaytime")` (current period). Night temps were overwriting highs. Fixed.
- **`anomaly.py` source_absence false positives** — used exact URL matching while `analyze_domain.py` uses domain-level matching. Switched to `urlparse().netloc` comparison.
- **`prepare_calendar` launch date parsing** — Added `"%Y-%m-%d %H:%MZ"` and `"%Y-%m-%d %H:%M"` to `_FORMATS`. Verified: `_parse_date("2026-04-15 14:30Z")` returns correct datetime.
- **Tag vocabulary mismatch** — `local` and `science` added to `cross_domain._VALID_TAGS`, `_TAG_LABELS`, and `_TAG_KEYWORDS`. All three modules (`validate.py`, `cross_domain.py`, `assemble.py`) now share identical 10-tag vocabulary. Contract tests verify consistency.
- **`cross_domain` prompt missing `why_it_matters`** — Added to deep_dives JSON schema in `_SYSTEM_PROMPT`. Template already renders it.

### UI / template improvements
- **At-a-glance voice labels** — Added SOURCES / ANALYSIS / THREAD micro-labels to each context block with distinct colors and a left-border visual separator for Analysis and Thread blocks.
- **AQI alert colors** — EPA-correct: red `#d32f2f` (Unhealthy 151–200), purple `#8f3f97` (Very Unhealthy 201–300), maroon `#7e0023` (Hazardous 301+). Previously all used `var(--down)` (always red).
- **AQI in weather bar** — Current AQI and label now shown inline in the weather bar: `Logan, UT — Clear · AQI 51 (Moderate)`.
- **Section order** — Moved Perspective Seams to follow Deep Dives (was between Cache Valley and Deep Dives).
- **Theme toggle** — Now injected inside `.wrapper` so it aligns with content; styled to match the dark chrome header instead of floating above the page.
- **Worth Reading** — Renamed "Weekend Reading · Friday Edition" to "Worth Reading", moved before Deep Dives. Now appears daily instead of Friday-only.

### Code cleanup
- **`_cross_domain_item_to_glance` + `_domain_item_to_glance` merged** into `_item_to_glance` in `stages/assemble.py`. Aliases kept for safety.
- **`stages/synthesize.py` and `digest.py`** — Deleted (confirmed dead code, neither in `config.yaml` pipeline manifest). References cleaned from `pipeline.py`.
- **Prompt files moved to `prompts/`** — `chat_briefer_prompt.md`, `weather-display-prompt.md`, `scripture_study_prompt.md`, `morning-digest-v2-plan.md` relocated and naming standardized to snake_case.
- **`modules/` directory created** — `modules/__init__.py` in place for weather Phase 2.
- **`pytest>=8.0` added to `requirements.txt`**.
- **`tests/` skeleton created** — `tests/__init__.py`, `tests/conftest.py`, `tests/test_prepare_local.py` (9 passing tests covering press release filter).
- **Git hygiene verified** — `output/` and `__pycache__/` properly ignored; no tracked runtime artifacts.
- **Configuration polish** — FreshRSS placeholder fields now have clarifying comments; `to_address` comment generalized from "your gmail address" to "your email address".
- **`sender.py` merged into `stages/send.py`** — `send_digest` inlined as `_send_digest`, root-level `sender.py` deleted.

### AQI editorial comment (weather spec)
- Added Utah DEQ action level language to `prompts/weather-display-prompt.md` Zone 1 spec.

### Weather Display Module (Phases 0–5 — COMPLETE)
- **Phase 0**: Added `AIRNOW_API_KEY=` to `.env.example`, expanded `config.yaml` weather block, added cache dir to Dockerfile, added cache to `.gitignore`.
- **Phase 1**: Rewrote `sources/weather.py` — NWS primary, Open-Meteo fallback, AirNow AQI, NOAA normals/records, JSON caching, precip classification.
- **Phase 2**: Created `modules/weather_display.py` — 5-zone SVG renderer with adaptive CSS, EPA AQI colors, email-safe markup, fallback chain.
- **Phase 3**: Integrated into pipeline — `prepare_weather` stage, `assemble` Markup wrapper, template `{% if weather_html %}` block, Google Fonts, `--wx-*` CSS variables.
- **Phase 4**: 109/109 tests passing across 3 test files + 7 JSON fixtures.
- **Phase 5**: Updated `README.md` with weather module docs, converted `prompts/weather-display-prompt.md` to implementation guide.
- **Bug fix**: Added `|safe` filter to `weather_html` in template (was being HTML-escaped despite `Markup()` wrapper).

### Cross-domain model comparison
- Tested 5 models (Kimi K2.5, Qwen3.6 Plus, Claude Sonnet 4, Claude Opus 4, Claude Opus 4.6) on cross-domain synthesis quality.
- Selected **Claude Opus 4.6** for cross_domain stage — best quality-to-cost ratio, hits all 3 bridge types, neutral framing.

### Pipeline quality fixes (2026-04-08)
- **At-a-glance cap enforcement** — `cross_domain.py` now enforces `digest.at_a_glance.max_items` (7) in post-processing, sorting by source_depth priority then cross_domain_note presence. Prompt updated to reference the config limit instead of hardcoded 12.
- **URL validation domain-level matching** — `analyze_domain.py` switched from exact URL matching to domain-level matching (`urlparse().netloc`), preventing false negatives when the LLM strips UTM params or normalizes URLs. Fixes false-positive `source_absence` anomaly warnings.
- **Econ domain sources expanded** — Added Financial Times, The Economist (Finance & Economics), and Reuters Markets to `config.yaml` econ-trade category (was only The Overshoot + Brad Setser).

### Infrastructure (2026-04-10)
- **Economic calendar wired in** — `stages/collect.py` now calls `fetch_economic_calendar()` from `sources/economic_calendar.py`; `stages/prepare_calendar.py` consumes `economic_calendar` events into the Week Ahead section.
- **Docker health check** — Added `HEALTHCHECK` to `Dockerfile` (checks `digest.log` recency within 25 hours).
- **Ruff linter added** — `ruff>=0.4` in `requirements.txt`, `ruff.toml` config (pyflakes F + critical pycodestyle E/W rules), `tests/test_lint.py` runs ruff as part of the pytest suite. Fixed all 17 lint issues: 6 unused imports (`sanitize.py`, `markets.py`, `weather.py`, `analyze_domain.py`, `cross_domain.py`, `seams.py`), 1 unused variable (`weather.py`), 8 empty f-strings, 2 unused variables in test file. 119 tests passing.
- **Contract tests added** — `tests/test_contracts.py` with 15 tests covering tag vocabulary consistency, launch date format round-trip, deep dive field contracts, `_empty_stage_output` coverage, and `_stage_artifact_key` coverage. All passing.

### Bug fixes (2026-04-10)
- **`llm.py` `_retry_loop` 4xx check before sleep** — Moved 4xx status code check BEFORE `time.sleep()` call. Bad API keys now fail immediately instead of wasting 10–20 seconds. Retry backoff only applies to 5xx/transient errors.
- **Duplicate `"cyber"` keyword** — Removed redundant entry from `cross_domain._TAG_KEYWORDS` (was under both tech and cyber sections).
- **Docker HEALTHCHECK false unhealthy reports** — Changed from log file recency check (1500 minutes) to process check (`pgrep -f entrypoint.py || pgrep -f pipeline.py`). Container no longer reports unhealthy between daily runs.
- **Weather normal interpolation discontinuity** — Fixed `_interpolate_monthly()` to use previous month's 15th as anchor for dates before the 15th, eliminating ~1.3°F step at month boundaries.
- **`entrypoint.py` crash-recovery test** — Fixed mock timing: `_next_run_time` now returns a past datetime so `now >= next_run` evaluates to True and `run()` is actually invoked. All 332 tests passing.

### Code quality (2026-04-10)
- **Consolidated `_collect_known_urls`** — Created `utils/urls.py` with shared `collect_known_urls()` function. Both `validate.py` and `stages/seams.py` now import from the shared utility. `seams.py` variant (which also includes domain analysis links) uses the optional `domain_analysis` parameter.
- **`validate.py` `VALID_TAG_LABELS` converted to dict** — Was a bare set of label strings, now a proper tag→label mapping (`{"war": "Conflict", ...}`) matching `cross_domain._TAG_LABELS`. Contract tests updated to verify dict equality and value consistency.

---

## Open items

### Test coverage gaps
_All source modules now have dedicated test coverage in `tests/test_sources.py` (rss_feeds, come_follow_me, holidays, economic_calendar, launches). Additional coverage added in `tests/test_cross_domain.py`, `tests/test_seams.py`, `tests/test_youtube.py`, `tests/test_markets.py`, `tests/test_stages.py`, `tests/test_assemble.py`, `tests/test_contracts.py`, and `tests/test_prepare_local.py`._
