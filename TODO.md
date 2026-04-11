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

---

## Open items

### Bugs

#### 1. `prepare_calendar` can't parse launch dates — launches always sort last
- **File**: `stages/prepare_calendar.py`, `_parse_date()` function (line ~25)
- **Problem**: `sources/launches.py` outputs dates like `"2026-04-15 14:30Z"` (format `%Y-%m-%d %H:%MZ`). The `_FORMATS` list in `prepare_calendar.py` has no matching pattern. All launch dates fall through to `datetime.max` and sort to the bottom.
- **Fix**: Add `"%Y-%m-%d %H:%MZ"` and `"%Y-%m-%d %H:%M"` to the `_FORMATS` list.
- **Test**: Call `_parse_date("2026-04-15 14:30Z")` and confirm it returns a valid datetime, not `datetime.max`.

#### 2. Tag vocabulary mismatch — `local` and `science` tags lost in cross_domain
- **Files**: `stages/cross_domain.py` (`_VALID_TAGS`, line ~32) and `stages/cross_domain.py` (`_normalize_tag()`, line ~134)
- **Problem**: `validate.py` and the CSS template recognize 10 tags: `{war, ai, domestic, defense, space, tech, local, science, econ, cyber}`. But `cross_domain._VALID_TAGS` only has 8 — missing `local` and `science`. The `_normalize_tag()` fallback maps unknown tags to `"domestic"`, so any item the LLM tags as `local` or `science` silently becomes `domestic` and gets the wrong CSS color and label.
- **Fix**: Add `"local"` and `"science"` to `_VALID_TAGS` in `cross_domain.py`. Add corresponding entries to `_TAG_LABELS`: `"local": "Local"`, `"science": "Science"`. Also update `_TAG_KEYWORDS` with some science keywords (e.g., `"climate"`, `"research"`, `"study"`).
- **Related**: `validate.py` `VALID_TAG_LABELS` uses short labels (`"US"`, `"Econ"`, `"War"`, `"Tech"`) while `cross_domain._TAG_LABELS` uses long labels (`"Politics"`, `"Economy"`, `"Conflict"`, `"Technology"`). The template renders `item.tag_label`, which comes from `cross_domain._TAG_LABELS` via `assemble._TAG_LABELS`. The `validate.py` labels are currently unused downstream — they should either be reconciled with the template labels or removed to avoid confusion.

#### 3. `cross_domain` prompt doesn't request `why_it_matters` for deep dives
- **Files**: `stages/cross_domain.py` (`_SYSTEM_PROMPT`, the deep_dives JSON schema ~line 213), `templates/email_template.py` (lines 499-502)
- **Problem**: The template renders `dive.why_it_matters` in a callout box (`{% if dive.why_it_matters %}`). The Phase 1 fallback path (`assemble._domain_item_to_deep_dive`) populates this from `deep_dive_rationale`. But the Phase 3 cross_domain prompt's JSON output schema for deep_dives has no `why_it_matters` field — only `headline`, `body`, `further_reading`, `source_depth`, and `domains_bridged`. So the callout box is always empty in Phase 3 mode.
- **Fix**: Add `"why_it_matters": "1-2 sentence summary of why this story matters beyond the headline"` to the deep_dives schema in `_SYSTEM_PROMPT`. The template already handles it.

### Integration tests to add

These tests would have caught bugs #1–3 above and should prevent similar regressions. They don't require Docker — they just import modules and compare their constants/contracts.

#### 4. `tests/test_contracts.py` — cross-module contract tests
Create a new test file with these checks:

- **Tag vocabulary consistency**: Import `VALID_TAGS` from `validate.py`, `_VALID_TAGS` from `stages/cross_domain.py`, `_TAG_LABELS` keys from `stages/assemble.py`. Assert all three sets are identical. Also parse the CSS in `templates/email_template.py` for `--tag-*-text:` patterns and assert the set of CSS tags matches `VALID_TAGS`. This catches bug #2.

- **Launch date format round-trip**: Import `fetch_upcoming_launches` output schema (construct a sample dict matching the keys returned by `sources/launches.py`) and pass its `"date"` value through `stages/prepare_calendar._parse_date()`. Assert it does NOT return `datetime.max`. This catches bug #1.

- **Deep dive field contract**: Import `_SYSTEM_PROMPT` from `stages/cross_domain.py` and parse the deep_dives JSON schema from it (or check for substring `"why_it_matters"`). Read `templates/email_template.py` source and extract all `dive.*` field references. Assert every template-referenced field appears in the prompt schema. This catches bug #3.

- **`_empty_stage_output` coverage**: Import `_NON_CRITICAL_STAGES` and `_empty_stage_output` from `pipeline.py`. Assert every non-critical stage returns a non-empty dict (not the `{}` default fallback).

- **`_stage_artifact_key` coverage**: Import `_stage_artifact_key` from `pipeline.py` and the stage names from `config.yaml`. Assert no stage falls through to the identity fallback (where key == stage name) unless that's intentional.

- **Tag label consistency**: Assert that `validate.VALID_TAG_LABELS` matches the values of `stages/cross_domain._TAG_LABELS` (or remove `VALID_TAG_LABELS` from `validate.py` if it's not used downstream).

### Minor / cosmetic

#### 7. Weather normal interpolation has a discontinuity at the 15th of each month
- **File**: `sources/weather.py`, `_interpolate_monthly()` (~line 553)
- **Problem**: The function anchors on the 15th of the current month and interpolates toward the 15th of the *next* month. For dates *before* the 15th (e.g., Feb 1), `frac` goes negative and gets clamped to 0.0, so Feb 1–14 all get the same normal as Feb 15. Meanwhile Jan 31 interpolates between Jan and Feb. This creates a ~1°F discontinuity at the month boundary.
- **Fix**: For dates before the 15th, interpolate between the *previous* month's 15th and the current month's 15th instead. Check if `day_of_year < day_15_this`; if so, use the previous month as the starting anchor.
- **Impact**: Low — normals are approximate and the error is ~1-2°F. But it's a visible staircase in the SVG chart at month boundaries.
