# Morning Digest — TODO

_Last updated: 2026-04-16_

---

## Open

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
