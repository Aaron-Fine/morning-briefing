# PR-0 — Instrumentation & Observability (design spec)

**Date:** 2026-05-30
**Epic:** `docs/plans/2026-05-24-Graph-Epic.md` (Phase 1, leading PR)
**Status:** design approved, ready for implementation plan

## Goal

Ship a per-run observability layer so every later keep-or-drop decision in
the Graph Epic is answerable from inspected test runs instead of guesswork.
PR-0 is observe-only — it changes no pipeline *behavior* — and it ends by
capturing the rendered-prompt baseline that PR-B will diff against.

Three classes of metric, all flowing **up the call stack** (no global mutable
collector): per-stage LLM usage, override-firing counts, and item-flow counts.
All land in a new `metrics` block inside the existing `run_meta.json`.

PR-0 also adds **runtime observability** — live, mid-run feedback about what is
executing and what we are waiting on, because today a run can sit silent for
minutes (parallel desks, long LLM calls, article fetches) with no signal of
progress vs. hang. This is the live face of the same wait boundaries the metrics
instrument: one touch per boundary, two outputs (a progress log line + the
recorded metric). See Component 6.

## Principle

Make the right thing the easy thing. Data rides with return values, so it is
structurally impossible to forget and there is no global state to reset. The
chosen shape forces each call site to acknowledge usage (tuple unpacking) and a
guard test fails CI if a stage makes an LLM call but doesn't surface usage.

## Non-goals

- No dollar cost baked into artifacts. Record tokens + model id; a config price
  table (`model_prices`) lets the Phase 5 smoke-detector view compute dollars at
  render time, so price changes never invalidate stored runs.
- No new parallel artifact. Metrics extend `run_meta.json`, not a separate
  `run_metrics.json` — one run-summary artifact, no drift, reuses the
  save-on-fatal-exit path.
- No behavior change. Overrides still fire exactly as today; PR-0 only *counts*
  when they mutate. PR-A removes the overrides and their counters together.

---

## Component 1 — LLM usage return contract

`morning_digest/llm.py` gains two NamedTuples and changes `call_llm`'s return:

```python
class LLMUsage(NamedTuple):
    model: str
    provider: str            # "fireworks" | "anthropic"
    tokens_in: int | None     # None when provider/stream didn't report usage
    tokens_out: int | None
    tokens_cached: int | None # cached portion of tokens_in; for cached-rate cost in Phase 5

class LLMResult(NamedTuple):
    value: dict | str        # json_mode → dict, else str (unchanged semantics)
    usage: LLMUsage
```

`tokens_cached` is recorded because Fireworks prices cached input separately
(the pricing table has distinct uncached/cached rates); without capturing the
cached split now, accurate cost derivation in Phase 5 is impossible.

`call_llm(...) -> LLMResult`. Every call site changes:

```python
result = call_llm(...)          # before
result, usage = call_llm(...)   # after — unpacking forces acknowledgment
```

The existing `isinstance(result, dict)` / `isinstance(result, str)` checks are
unchanged; they now operate on the unpacked `value`.

**Call sites (11) and the three wrappers that thread usage through:**
- `stages/enrich_articles/canonical.py:95`
- `stages/compress.py:45`
- `stages/coverage_gaps.py:206`
- `stages/prepare_spiritual_weekly.py:127, 297`
- `stages/analyze_domain.py:674` (inside the per-desk worker — desk result
  carries usage up to `_run_all_domains`)
- `cross_domain/stage.py:45, 57` (helper functions — return `(value, usage)`)
- `stages/seams.py:590, 611, 673` (`_call_turn_json` wrapper returns
  `(dict, usage)`)

**Usage extraction by provider** (Fireworks shapes verified against the live API
2026-05-30, model `minimax-m2p7`):
- Fireworks (OpenAI-compatible): `resp.usage.prompt_tokens` /
  `completion_tokens`, and `resp.usage.prompt_tokens_details.cached_tokens`.
  **Streaming** (used when `max_tokens > 4096`) with
  `stream_options={"include_usage": True}` — **confirmed working**: usage arrives
  in a *final chunk where `choices == []` and `usage` is populated*, immediately
  before `data: [DONE]`. Every *intermediate* chunk carries `usage: null`, so the
  extractor must keep the last non-null `usage` seen (and must read it before the
  existing `if not chunk.choices: continue` guard, since the usage chunk has empty
  choices). If `include_usage` is ever unsupported by a model, `tokens_*` = `None`
  and `usage_missing` increments — but it is supported on the endpoint today.
- Anthropic: `resp.usage.input_tokens` / `output_tokens` (`cached_tokens` left
  `None` — Anthropic reports cache reads under different fields not plumbed here).

**Missing-usage honesty:** when `tokens_*` is `None`, aggregation counts it as 0
toward sums but increments a `usage_missing` counter so the smoke detector shows
real coverage rather than fake zeros.

**Failure/fallback paths:** when a call ultimately fails and returns a fallback
value, `usage` is `LLMUsage(model, provider, None, None)` (a real call may not
have completed). The retry loop reports usage from the successful attempt only.

---

## Component 2 — Stage → run_meta fold

Each stage collects its `LLMUsage` records and returns them under a reserved
output key:

```python
return {..., "llm_usage": [usage_a, usage_b, ...]}
```

A helper `morning_digest/metrics.py::aggregate_usage(records) -> dict` sums
tokens per model and reports `usage_missing` coverage.

**Reserved output keys** carry metrics up without becoming artifacts:
`llm_usage` (Component 2), `override_counts` (Component 3), and
`domain_research_metrics` (from `analyze_domain`). The run loop, after
`context.update(outputs)` and **before** the per-key artifact-save loop, pops
all three so they are never written as stray artifacts and never collide between
stages, then folds them into `run_meta`:

```python
run_meta["metrics"]["stages"][stage_name] = {
    "model": <dominant model id for the stage>,
    "tokens_in": <sum>, "tokens_out": <sum>,
    "usage_missing": <int>,
    "latency_s": <already tracked>,
    "retries": <from _run_with_retry>,
    "items_in": <generic, see Component 4>,
    "items_out": <generic, see Component 4>,
}
```

Note: mark speculative or future use keys with a TODO in the code for future stages to update as needed. 

`retries` requires `_run_with_retry` to report attempt count back to the loop
(today it only logs). Minimal change: return `(outputs, attempts)` or stash the
count where the loop can read it.

**Guard test:** a test enumerates stage modules that import `call_llm` and
asserts each surfaces `llm_usage` in its outputs on a representative mocked run.
A stage that adds an LLM call but forgets the reserved key fails CI.

---

## Component 3 — Override-firing counts (all five, return-up)

No global counter. Each override reports whether it mutated; the parse/analyze
layer tallies into an `override_counts` dict returned in stage outputs and
folded by the runner into `run_meta["metrics"]["overrides"]`.

| Override | File | "Fired" means |
|---|---|---|
| `_recompute_source_depth` | `cross_domain/parse.py:452` | recomputed value differs from the LLM's emitted `source_depth` |
| `_normalize_tag` | `cross_domain/parse.py:180` | remapped an off-vocabulary tag (input ≠ output) |
| `tag_label` reassignment | `cross_domain/parse.py:603` | assigned label differs from the LLM's emitted `tag_label` |
| `_ensure_primary_glance_coverage` | `cross_domain/parse.py:318` | count of primary-tag items re-injected |
| `_rebalance_categories` | `stages/analyze_domain.py:757` | count of synthesized fallback items (already produces `rebalance_log`) |

Signature changes are additive: e.g. `_recompute_source_depth` returns
`(value, changed: bool)`; callers at `parse.py:473, 488` accumulate. Each
override that fires zero times across the test runs is a candidate for outright
deletion in PR-A; one that fires often is evidence the LLM genuinely can't do
that work, so PR-A's fix is "derive in Python, drop the prompt instruction."

Resulting shape:

```python
run_meta["metrics"]["overrides"] = {
    "recompute_source_depth": 4,
    "normalize_tag": 11,
    "tag_label": 6,
    "ensure_primary_glance_coverage": 1,
    "rebalance_categories": 2,
}
```

---

## Component 4 — Item-flow counts (generic, runner-derived)

Computed in the run loop, not in stages. After a stage runs, the loop produces
`items_out` as a per-stage breakdown of the list-valued entries in `outputs`
with their lengths (and nested list lengths under known container keys). Kept
deliberately simple and generic so stages stay clean and new stages get
item-flow for free.

`items_in` is **best-effort**: where a stage has one obvious input collection
(e.g. `cluster_articles`/`analyze_domain` consuming `raw_sources["rss"]`) the
loop records its size; where there is no single clean input, `items_in` is
omitted rather than guessed. The source_depth distribution (needed for PR-C/PR-E)
is read generically from the `at_a_glance` / desk items present in `outputs`.

---

## Component 5 — PR-B prompt baseline (global-free, end of PR-0)

A `--capture-prompts <dir>` CLI flag puts the dir into the runner's `_obs`
context (see below). When present, `call_llm` writes the exact `system_prompt` +
`user_content` it is about to send to `<dir>/<stage>__<seq>.txt`, where `<seq>`
is a **per-stage** counter derived from existing files on disk (not a global
counter — that would number across stages and make the baseline diff
non-deterministic). No globals.

Procedure (run at the end of PR-0, committed as the baseline fixture):
1. Pick a saved artifact day as the frozen upstream fixture.
2. Run the LLM stages from cached artifacts (`--stage <name>`), so only prompt
   *assembly* varies, with `--capture-prompts output/prompt_baseline/`.
3. Commit the captured prompts as the reference baseline.

PR-B re-runs the identical frozen fixture and diffs against this baseline. With
`audience.yaml` populated with today's values, rendered prompts should be
byte-identical; any unintended delta is a threading bug.

**The observability context channel (`_obs`).** Runner-to-`call_llm` metadata —
stage name, optional sublabel, optional capture dir — travels in a single
namespaced key `model_config["_obs"]` (a dict), set once per stage in the run
loop. `call_llm` reads it with `.get` and never pops or splats it, so it cannot
leak into a provider call. This is deliberately *not* three scattered
`_stage_name`/`_sublabel`/`_capture_prompts_dir` keys (a landmine the day someone
does `client.create(**model_config)`), and deliberately *not* `contextvars`
(propagating them into `analyze_domain`'s desk `ThreadPoolExecutor` is more
machinery than a single-user batch warrants). Given the runner→stage→`call_llm`
flow — where the runner pre-seeds and the stage forwards `model_config`
unchanged — a single read-only key on that already-threaded dict is the
proportionate channel.

---

## Component 6 — Runtime observability (live progress + heartbeat)

Live mid-run feedback over stdlib `logging` at INFO, so it works identically in
a terminal, under cron, and in Docker logs — no TTY assumptions, no new
dependency. Two pieces: per-boundary progress lines, and a heartbeat watchdog
that proves the run is alive.

**`morning_digest/progress.py`** provides:
- A thread-safe **in-flight registry**: `label -> started_at`. Parallel desks
  register concurrently, so access is lock-guarded.
- A **`track(label)` context manager**: on enter, registers the op and logs
  `<label>: start`; on exit, deregisters and logs `<label>: done {elapsed}s`.
  This is the single wait-boundary primitive.
- A **heartbeat daemon thread**, started at pipeline start and stopped in a
  `finally` at pipeline end. Every `heartbeat_interval_s` (config, default 15;
  `<= 0` disables) it logs one line summarizing the current in-flight set:
  `[hb] waiting on N op(s): <labels> ({longest_elapsed}s)`. Quiet when nothing
  is in flight. Daemon so it can never block process exit.

**Wait points instrumented** (these are the same boundaries Components 1–3
touch):
- **Run loop**: extend the existing stage banner to `--- Stage N/M: name ---`.
- **`call_llm`**: wrap the provider call in `track(f"{stage}[:{sublabel}] {model}")`;
  the done-line carries elapsed + token count. Replaces the bare
  `Calling LLM ({model})...` log. `stage`/`sublabel` arrive via the `_obs` context
  key described in Component 5 (sublabel, e.g. a desk key, is optional and set by
  `analyze_domain`'s desk worker).
- **`analyze_domain` desk pool**: each desk wraps its work in
  `track(f"desk {desk_key}")`; completion logs a running `N/M desks done`.
- **`enrich_articles` fetch loop**: periodic `fetched X/Y articles` on its batch
  boundary.

**Separation of concerns:** `track()` owns *liveness* (logs + heartbeat
registration + wall-clock timing); the `LLMResult.usage` return owns *metrics*
(tokens/model). They co-locate at `call_llm` but neither depends on the other —
runtime observability works even if a provider omits usage, and metrics fold up
even if the heartbeat is disabled.

---

## Data shape (full `run_meta.metrics`)

```jsonc
"metrics": {
  "stages": {
    "analyze_domain": {
      "model": "minimax-m2p7", "tokens_in": 24800, "tokens_out": 3100,
      "tokens_cached": 1900, "usage_missing": 0, "latency_s": 12.4, "retries": 0,
      "items_out": {"domain_analysis.items": 51}
    }
    // ... one per stage that ran
  },
  "overrides": { "recompute_source_depth": 4, "normalize_tag": 11, ... },
  "domain_research": { "fired": 2, "articles_fetched": 7, "changed_output": true },
  "totals": { "tokens_in": <sum>, "tokens_out": <sum>, "usage_missing": <int> }
}
```

`domain_research` fields come from the existing loop in `analyze_domain`
(`_run_domain_research`); the stage returns them under the reserved
`domain_research_metrics` output key and the runner folds them to
`metrics.domain_research`. PR-0 surfaces fire count, articles fetched, and a
boolean for whether the second pass changed desk output.

## Extensibility

The `metrics` block is designed to be appended to, not rewritten. Later phases
add their own sub-keys (PR-D: index/candidate stats; Phase 3: lexical-miss
counts) under the same artifact. The price table (`model_prices` in config) and
the smoke-detector rendering arrive in Phase 5; PR-0 only produces the data.

## Testing (TDD)

- `LLMUsage`/`LLMResult` extraction from Fireworks (non-stream + stream
  with/without `include_usage`) and Anthropic response shapes; missing-usage → `None`.
- Runner fold: reserved keys popped (not saved as artifacts), timing/retries
  attached, `aggregate_usage` sums + coverage.
- Each override's `changed` signal: mutating vs. non-mutating input.
- Guard test: every `call_llm`-importing stage surfaces `llm_usage`.
- Generic item-flow derivation from representative `outputs`.
- `--capture-prompts` writes the expected files with exact prompt content; no-op
  when the flag is absent.
- `progress.track()` registers/deregisters and logs start + `done {elapsed}s`;
  in-flight registry is correct under concurrent register/deregister. The
  heartbeat *message-formatting* function is tested directly (given an in-flight
  set → expected line) so no flaky timer/sleep is needed; the daemon thread's
  start/stop lifecycle is tested for clean shutdown, and `interval <= 0` disables.
- All provider calls mocked; no live LLM.

**Test-churn mitigation.** Changing `call_llm`'s return type breaks ~60 existing
mock sites across 11 test files (they return bare dicts via `side_effect`). A
`tests/conftest.py` helper `llm_result(value, tokens_in=…, tokens_out=…)` wraps a
value in an `LLMResult` so the updates are a mechanical
`[d1, d2]` → `[llm_result(d1), llm_result(d2)]`; usage-asserting tests pass real
token counts.

## Out of scope for PR-0 (carried by later PRs)

- Dollar-cost rendering and the smoke-detector view (Phase 5).
- Index/candidate metrics (PR-D), lexical-miss metrics (Phase 3).
- Removing any override (PR-A).
- Threading `audience.yaml` / consuming the baseline (PR-B).
