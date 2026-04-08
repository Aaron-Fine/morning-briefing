# Morning Digest — TODO

_Last updated: 2026-04-08_

---

## Done this session

### Bug fixes
- **`--force-friday` was broken** — only passed to `synthesize` (dead stage). Fixed: now passed to `cross_domain` in `pipeline.py`; `cross_domain.py` updated to accept `force_friday` kwarg and pass it to `_build_input`.
- **Press release filter** — `stages/prepare_local.py` now filters items with `/press_releases/` in URL or PRNewswire/BusinessWire markers in summary.
  - **Bonus bug found and fixed**: `PRNewswire` (without slashes) wasn't caught in summaries. Changed `/PRNewswire/` → `PRNewswire` in `_WIRE_MARKERS`.

### UI / template improvements
- **At-a-glance voice labels** — Added SOURCES / ANALYSIS / THREAD micro-labels to each context block with distinct colors and a left-border visual separator for Analysis and Thread blocks.
- **AQI alert colors** — EPA-correct: red `#d32f2f` (Unhealthy 151–200), purple `#8f3f97` (Very Unhealthy 201–300), maroon `#7e0023` (Hazardous 301+). Previously all used `var(--down)` (always red).
- **AQI in weather bar** — Current AQI and label now shown inline in the weather bar: `Logan, UT — Clear · AQI 51 (Moderate)`.
- **Section order** — Moved Perspective Seams to follow Deep Dives (was between Cache Valley and Deep Dives).
- **Theme toggle** — Now injected inside `.wrapper` so it aligns with content; styled to match the dark chrome header instead of floating above the page.

### Code cleanup
- **`_cross_domain_item_to_glance` + `_domain_item_to_glance` merged** into `_item_to_glance` in `stages/assemble.py`. Aliases kept for safety.
- **`stages/synthesize.py` and `digest.py`** — Deleted (confirmed dead code, neither in `config.yaml` pipeline manifest). References cleaned from `pipeline.py`.
- **Prompt files moved to `prompts/`** — `chat_briefer_prompt.md`, `weather-display-prompt.md`, `scripture_study_prompt.md`, `morning-digest-v2-plan.md` relocated and naming standardized to snake_case.
- **`modules/` directory created** — `modules/__init__.py` in place for weather Phase 2.
- **`pytest>=8.0` added to `requirements.txt`**.
- **`tests/` skeleton created** — `tests/__init__.py`, `tests/conftest.py`, `tests/test_prepare_local.py` (9 passing tests covering press release filter).
- **Git hygiene verified** — `output/` and `__pycache__/` properly ignored; no tracked runtime artifacts.
- **Configuration polish** — FreshRSS placeholder fields now have clarifying comments; `to_address` comment generalized from "your gmail address" to "your email address".

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
- **UI change**: Renamed "Weekend Reading · Friday Edition" to "Worth Reading", moved before Deep Dives.

---

## Other open items

### Docker rebuild reminder
Code changes require a rebuild — only `config.yaml` and `output/` are volume-mounted:
```bash
docker compose build && docker compose up -d
```

### `.env` — add when starting weather Phase 0
```
AIRNOW_API_KEY=<your_key>
```
