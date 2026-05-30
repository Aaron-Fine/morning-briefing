# PR-0 Instrumentation & Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-run observability (LLM usage, override-firing counts, item-flow) into `run_meta.json`, plus live mid-run progress logging with a heartbeat, and a `--capture-prompts` flag that produces the PR-B baseline — all observe-only, no pipeline behavior change.

**Architecture:** LLM usage flows *up the call stack* — `call_llm` returns an `LLMResult(value, usage)` NamedTuple, stages surface usage under reserved output keys, and the run loop folds them into `run_meta["metrics"]`. Override functions report when they mutate. Runtime observability is a thread-safe `progress.track()` primitive plus a heartbeat daemon, sharing the same wait boundaries. No global mutable metrics collector.

**Tech Stack:** Python 3.12, pytest, `unittest.mock`, stdlib `logging`/`threading`, OpenAI SDK (Fireworks), Anthropic SDK.

**Spec:** `docs/superpowers/specs/2026-05-30-pr0-instrumentation-design.md`

---

## File Structure

**New files:**
- `morning_digest/metrics.py` — `LLMUsage`/`LLMResult` re-export, `aggregate_usage()`, override-count helpers, item-flow helpers.
- `morning_digest/progress.py` — `track()` context manager, in-flight registry, `Heartbeat` daemon.
- `tests/test_metrics.py`, `tests/test_progress.py`, `tests/test_pr0_instrumentation.py` (runner integration + guard test).

**Modified files:**
- `morning_digest/llm.py` — `LLMUsage`/`LLMResult` types; usage extraction; `call_llm` returns `LLMResult`; prompt capture; progress wrap.
- `pipeline.py` — run loop: stage banner `N/M`, reserved-key pop + fold into `run_meta["metrics"]`, item-flow, `_run_with_retry` attempt count, heartbeat lifecycle, `--capture-prompts` flag, `_obs` context threading.
- `cross_domain/stage.py`, `stages/seams.py`, `stages/analyze_domain.py`, `stages/compress.py`, `stages/coverage_gaps.py`, `stages/prepare_spiritual_weekly.py`, `stages/enrich_articles/canonical.py` — unpack `LLMResult`, collect + surface `llm_usage`.
- `cross_domain/parse.py`, `stages/analyze_domain.py` — surface `override_counts`.
- `tests/conftest.py` — `llm_result()` helper.
- ~11 test files — mechanical mock updates.

**Note on the `_obs` context:** the runner sets a single `model_config["_obs"]` dict — `{"stage": <name>, "capture_dir"?: <path>}` — once per stage; `analyze_domain`'s desk worker merges in `"sublabel"`. `call_llm` reads it with `.get`, never pops or splats it into a provider call. It is metadata-only and ignored when absent. (Rationale — why one namespaced key, not three scattered keys, and not contextvars — is in the spec, Component 5.)

---

## Task 1: LLMResult return contract + usage extraction

**Files:**
- Modify: `morning_digest/llm.py`
- Test: `tests/test_llm.py` (existing), `tests/conftest.py`

- [ ] **Step 1: Write failing test for the new types and Fireworks non-stream usage**

Add to `tests/test_llm.py`:

```python
from unittest.mock import MagicMock, patch
from morning_digest.llm import call_llm, LLMResult, LLMUsage


def _fireworks_resp(content, prompt_tokens=12, completion_tokens=7, cached_tokens=3):
    # Verified shape (2026-05-30): usage has prompt_tokens_details.cached_tokens.
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    resp.usage.prompt_tokens_details.cached_tokens = cached_tokens
    return resp


@patch("morning_digest.llm._fireworks_client")
def test_call_llm_returns_llmresult_with_usage(mock_client):
    mock_client.return_value.chat.completions.create.return_value = _fireworks_resp(
        '{"ok": true}'
    )
    out = call_llm("sys", "user", {"provider": "fireworks", "model": "m", "max_tokens": 100}, stream=False)
    assert isinstance(out, LLMResult)
    assert out.value == {"ok": True}
    assert out.usage == LLMUsage("m", "fireworks", tokens_in=12, tokens_out=7, tokens_cached=3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm.py::test_call_llm_returns_llmresult_with_usage -v`
Expected: FAIL — `ImportError: cannot import name 'LLMResult'`.

- [ ] **Step 3: Add types and thread usage through Fireworks**

In `morning_digest/llm.py`, after the imports/log (around line 21) add:

```python
from typing import NamedTuple


class LLMUsage(NamedTuple):
    model: str
    provider: str
    tokens_in: int | None
    tokens_out: int | None
    tokens_cached: int | None = None   # cached portion of tokens_in (Fireworks prompt_tokens_details)


class LLMResult(NamedTuple):
    value: dict | str
    usage: LLMUsage
```

Change `_fireworks_call` to return `(text, tokens_in, tokens_out)`. Replace its body's two `return` paths:

```python
def _usage_tuple(usage):
    """Extract (tokens_in, tokens_out, tokens_cached) from a Fireworks usage object.

    Verified live 2026-05-30: usage.prompt_tokens / completion_tokens, and
    usage.prompt_tokens_details.cached_tokens (cached_tokens=0 when none).
    """
    if not usage:
        return None, None, None
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", None) if details else None
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        cached,
    )


def _fireworks_call(client, create_kwargs: dict, stream: bool):
    if stream:
        kwargs = {**create_kwargs, "stream": True, "stream_options": {"include_usage": True}}
        content_chunks: list[str] = []
        saw_reasoning_content = False
        empty_count = 0
        tokens_in = tokens_out = tokens_cached = None
        with client.chat.completions.create(**kwargs) as resp:
            for chunk in resp:
                # Verified: usage arrives on a FINAL chunk with choices == [];
                # intermediate chunks carry usage == null. Read before the
                # empty-choices guard so the usage chunk isn't skipped.
                if getattr(chunk, "usage", None):
                    tokens_in, tokens_out, tokens_cached = _usage_tuple(chunk.usage)
                if not chunk.choices:
                    empty_count += 1
                    if empty_count > 500:
                        log.warning("Fireworks stream: >500 empty chunks, breaking")
                        break
                    continue
                empty_count = 0
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    content_chunks.append(delta.content)
                elif getattr(delta, "reasoning_content", None):
                    saw_reasoning_content = True
        text = "".join(content_chunks).strip()
        if not text and saw_reasoning_content:
            log.warning(
                "Fireworks stream: reasoning_content received without assistant content; "
                "ignoring reasoning trace"
            )
        return text, tokens_in, tokens_out, tokens_cached
    else:
        kwargs = {**create_kwargs, "stream": False}
        resp = client.chat.completions.create(**kwargs)
        text = (resp.choices[0].message.content or "").strip()
        tokens_in, tokens_out, tokens_cached = _usage_tuple(getattr(resp, "usage", None))
        return text, tokens_in, tokens_out, tokens_cached
```

In `_call_fireworks`, replace the `_retry_loop(...)` + `return _parse_response(...)` tail:

```python
    raw, tokens_in, tokens_out, tokens_cached = _retry_loop(
        lambda: _fireworks_call(client, create_kwargs, stream),
        max_retries,
        retryable,
        model,
    )
    return LLMResult(
        _parse_response(raw, json_mode, model),
        LLMUsage(model, "fireworks", tokens_in, tokens_out, tokens_cached),
    )
```

The `_retry_loop` `fn()` now returns a 4-tuple; `_retry_loop` already returns whatever `fn()` returns, so no signature change is needed beyond its return annotation (drop `-> str`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm.py::test_call_llm_returns_llmresult_with_usage -v`
Expected: PASS.

- [ ] **Step 5: Write failing test for streaming usage + Anthropic**

Add to `tests/test_llm.py`:

```python
@patch("morning_digest.llm._fireworks_client")
def test_fireworks_stream_usage_from_final_chunk(mock_client):
    # Mirrors the verified live shape: usage on a final choices==[] chunk;
    # intermediate text chunk has usage == None.
    usage_chunk = MagicMock(
        choices=[],
        usage=MagicMock(prompt_tokens=100, completion_tokens=40,
                        prompt_tokens_details=MagicMock(cached_tokens=12)),
    )
    text_chunk = MagicMock()
    text_chunk.choices = [MagicMock()]
    text_chunk.choices[0].delta.content = "hello"
    text_chunk.usage = None
    stream_cm = MagicMock()
    stream_cm.__enter__.return_value = iter([text_chunk, usage_chunk])
    stream_cm.__exit__.return_value = False
    mock_client.return_value.chat.completions.create.return_value = stream_cm
    out = call_llm("s", "u", {"provider": "fireworks", "model": "m", "max_tokens": 8000}, json_mode=False)
    assert out.value == "hello"
    assert out.usage.tokens_in == 100 and out.usage.tokens_out == 40
    assert out.usage.tokens_cached == 12


@patch("morning_digest.llm._anthropic_client")
def test_anthropic_usage(mock_client):
    msg = MagicMock()
    msg.content = [MagicMock(text="result text")]
    msg.usage = MagicMock(input_tokens=33, output_tokens=9)
    mock_client.return_value.messages.create.return_value = msg
    out = call_llm("s", "u", {"provider": "anthropic", "model": "claude-x"}, json_mode=False, stream=False)
    assert out.value == "result text"
    assert out.usage == LLMUsage("claude-x", "anthropic", 33, 9)
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest tests/test_llm.py -k "stream_usage or anthropic_usage" -v`
Expected: FAIL (Anthropic still returns a bare str; stream path returns str).

- [ ] **Step 7: Thread usage through Anthropic**

In `_call_anthropic`, replace `_do_call` and the tail:

```python
    def _do_call():
        if stream:
            with client.messages.stream(**create_kwargs) as s:
                text = s.get_final_text().strip()
                msg = s.get_final_message()
                u = getattr(msg, "usage", None)
                return text, getattr(u, "input_tokens", None), getattr(u, "output_tokens", None)
        else:
            resp = client.messages.create(**create_kwargs)
            u = getattr(resp, "usage", None)
            return resp.content[0].text.strip(), getattr(u, "input_tokens", None), getattr(u, "output_tokens", None)

    retryable = (
        anthropic.APIStatusError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
    )
    raw, tokens_in, tokens_out = _retry_loop(_do_call, max_retries, retryable, model)
    return LLMResult(
        _parse_response(raw, json_mode, model),
        LLMUsage(model=model, provider="anthropic", tokens_in=tokens_in, tokens_out=tokens_out),
    )
```

Update `call_llm`'s return annotation to `-> LLMResult` and its docstring's Returns line.

- [ ] **Step 8: Run to verify passes**

Run: `pytest tests/test_llm.py -k "stream_usage or anthropic_usage" -v`
Expected: PASS.

- [ ] **Step 9: Add the conftest helper**

In `tests/conftest.py` add:

```python
from morning_digest.llm import LLMResult, LLMUsage


def llm_result(value, tokens_in=10, tokens_out=5, model="test-model", provider="fireworks"):
    """Wrap a mock LLM value in an LLMResult for call_llm mocks."""
    return LLMResult(value, LLMUsage(model, provider, tokens_in, tokens_out))
```

Make it importable in tests by also exposing it as a fixture-free module function (tests import it directly: `from tests.conftest import llm_result`). If the project uses `conftest` autouse only, add `pytest.fixture`-wrapped variant too:

```python
import pytest

@pytest.fixture
def make_llm_result():
    return llm_result
```

- [ ] **Step 10: Commit**

```bash
git add morning_digest/llm.py tests/test_llm.py tests/conftest.py
git commit -m "feat(llm): call_llm returns LLMResult(value, usage)"
```

---

## Task 2: Update production call sites to unpack LLMResult

**Files:**
- Modify: `cross_domain/stage.py:38-64`, `stages/seams.py:582-630,673`, `stages/analyze_domain.py:674`, `stages/compress.py:45`, `stages/coverage_gaps.py:206`, `stages/prepare_spiritual_weekly.py:127,297`, `stages/enrich_articles/canonical.py:95`

The mechanical transform at every site: `X = call_llm(...)` → `X, _usage = call_llm(...)` (the `_usage` is collected in Task 5; for now discard with `_`). Wrappers that `return call_llm(...)` return `(value, usage)`.

- [ ] **Step 1: Update the single-call stages (discard usage for now)**

`stages/compress.py:45`:
```python
        compressed, _usage = call_llm(
```
`stages/coverage_gaps.py:206`:
```python
        result, _usage = call_llm(
```
`stages/enrich_articles/canonical.py:95`:
```python
        summary, _usage = call_llm(
```
`stages/prepare_spiritual_weekly.py:127` and `:297`:
```python
    guide, _usage = call_llm(      # line 127
        ...
        raw, _usage = call_llm(    # line 297
```
`stages/analyze_domain.py:674`:
```python
        result, _usage = call_llm(
```

- [ ] **Step 2: Update the cross_domain wrapper**

`cross_domain/stage.py` `_call_turn_json` — return `(dict, usage)`:
```python
def _call_turn_json(prompt, user_content, model_config, turn_name):
    try:
        value, usage = call_llm(prompt, user_content, model_config, max_retries=2, json_mode=True, stream=True)
        return value, usage
    except Exception as exc:
        log.warning(f"cross_domain: {turn_name} turn failed with streaming, retrying once: {exc}")
        value, usage = call_llm(prompt, user_content, model_config, max_retries=2, json_mode=True, stream=False)
        return value, usage
```
Then at its two call sites (`cross_domain_plan = _call_turn_json(...)` ~line 106, `result = _call_turn_json(...)` ~line 134) unpack: `cross_domain_plan, _usage = _call_turn_json(...)` and `result, _usage = _call_turn_json(...)`.

- [ ] **Step 3: Update the seams wrapper**

`stages/seams.py` `_call_turn_json` (line 582) returns `(dict|str, usage)`. The function currently calls `call_llm` at lines 590 and 611 and inspects `result`/`raw`. Rewrite so each `call_llm` is unpacked and the function returns `(parsed, usage)`:
```python
    try:
        value, usage = call_llm(prompt, user_content, model_config, max_retries=1, json_mode=True, stream=False)
        if isinstance(value, dict):
            return value, usage
        if isinstance(value, str):
            return _parse_turn_json(value), usage
    except Exception as exc:
        log.warning(f"seams: {turn_name} turn failed with provider JSON mode, falling back to raw parse: {exc}")
    last_usage = None
    raw_attempts: list[str] = []
    for stream in (True, False):
        try:
            raw, last_usage = call_llm(prompt, user_content, model_config, max_retries=1, json_mode=False, stream=stream)
            ...  # existing raw handling, returning (parsed, last_usage)
```
And the standalone `return call_llm(...)` at line 673 becomes `value, usage = call_llm(...); return value, usage` (caller unpacks). Update its caller to unpack.

- [ ] **Step 4: Run the full suite to find broken mocks**

Run: `pytest -q`
Expected: many FAILs in the 11 test files that mock `call_llm` (they return bare dicts; production now unpacks two values). This is expected — Task 3 fixes them.

- [ ] **Step 5: Commit**

```bash
git add cross_domain/stage.py stages/
git commit -m "refactor: unpack LLMResult at all call_llm sites"
```

---

## Task 3: Update test mocks to return LLMResult

**Files:**
- Modify: `tests/test_analyze_domain.py`, `tests/test_cross_domain.py`, `tests/test_cross_domain_two_turn.py`, `tests/test_seams.py`, `tests/test_seam_annotations.py`, `tests/test_enrich_articles.py`, `tests/test_coverage_gaps.py`, `tests/test_prepare_spiritual_weekly.py`, `tests/test_new_desks.py`, `tests/test_stages.py`

Mechanical transform. Each `mock_llm.side_effect = [a, b, ...]` or `.return_value = a` where `a` is a dict/str becomes wrapped with `llm_result(...)`. Import `from tests.conftest import llm_result` at the top of each file.

- [ ] **Step 1: Add the import to each test file**

At the top of each of the 10 files: `from tests.conftest import llm_result`.

- [ ] **Step 2: Wrap return values — example transform**

Before (`tests/test_cross_domain.py:287`):
```python
        mock_llm.side_effect = [
            {"deep_dives": [...], ...},
            {"at_a_glance": [...], ...},
        ]
```
After:
```python
        mock_llm.side_effect = [
            llm_result({"deep_dives": [...], ...}),
            llm_result({"at_a_glance": [...], ...}),
        ]
```
Apply the identical wrap to every dict/str return across all 60 sites. For `return_value = "..."` use `llm_result("...")`.

- [ ] **Step 3: Run the suite green**

Run: `pytest -q`
Expected: PASS (all previously-green tests pass again).

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: wrap call_llm mocks in llm_result()"
```

---

## Task 4: progress.py — track() + in-flight registry

**Files:**
- Create: `morning_digest/progress.py`
- Test: `tests/test_progress.py`

- [ ] **Step 1: Write failing test**

`tests/test_progress.py`:
```python
import logging
from morning_digest import progress


def test_track_logs_start_and_done(caplog):
    progress.reset()
    with caplog.at_level(logging.INFO):
        with progress.track("desk ai_tech"):
            assert progress.in_flight_labels() == ["desk ai_tech"]
    assert progress.in_flight_labels() == []
    msgs = [r.message for r in caplog.records]
    assert any("desk ai_tech: start" in m for m in msgs)
    assert any("desk ai_tech: done" in m for m in msgs)


def test_heartbeat_line_formats_in_flight():
    progress.reset()
    with progress.track("a"):
        with progress.track("b"):
            line = progress.heartbeat_line()
    assert line is not None
    assert "waiting on 2 op" in line
    assert "a" in line and "b" in line


def test_heartbeat_line_quiet_when_idle():
    progress.reset()
    assert progress.heartbeat_line() is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_progress.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement progress.py**

```python
"""Runtime observability: live progress logging + heartbeat.

Thread-safe because analyze_domain runs desks across a ThreadPoolExecutor.
No metrics live here — this is liveness only (see morning_digest/metrics.py).
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager

log = logging.getLogger("morning_digest.progress")

_lock = threading.Lock()
_in_flight: dict[str, float] = {}


def reset() -> None:
    with _lock:
        _in_flight.clear()


def in_flight_labels() -> list[str]:
    with _lock:
        return list(_in_flight)


@contextmanager
def track(label: str):
    start = time.monotonic()
    with _lock:
        _in_flight[label] = start
    log.info("  %s: start", label)
    try:
        yield
    finally:
        with _lock:
            _in_flight.pop(label, None)
        log.info("  %s: done %.1fs", label, time.monotonic() - start)


def heartbeat_line() -> str | None:
    now = time.monotonic()
    with _lock:
        if not _in_flight:
            return None
        labels = list(_in_flight)
        longest = max(now - t for t in _in_flight.values())
    shown = ", ".join(labels[:5]) + ("…" if len(labels) > 5 else "")
    return f"[hb] waiting on {len(labels)} op(s): {shown} ({longest:.0f}s)"
```

- [ ] **Step 4: Run to verify passes**

Run: `pytest tests/test_progress.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add morning_digest/progress.py tests/test_progress.py
git commit -m "feat(progress): track() context manager + in-flight registry"
```

---

## Task 5: Heartbeat daemon

**Files:**
- Modify: `morning_digest/progress.py`
- Test: `tests/test_progress.py`

- [ ] **Step 1: Write failing test (lifecycle, no flaky sleep)**

```python
def test_heartbeat_daemon_starts_and_stops():
    progress.reset()
    hb = progress.Heartbeat(interval_s=0.05)
    hb.start()
    assert hb._thread is not None and hb._thread.is_alive()
    hb.stop()
    assert not hb._thread.is_alive()


def test_heartbeat_disabled_when_interval_non_positive():
    hb = progress.Heartbeat(interval_s=0)
    hb.start()
    assert hb._thread is None
    hb.stop()  # no-op, must not raise
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_progress.py -k heartbeat_daemon -v`
Expected: FAIL — `Heartbeat` missing.

- [ ] **Step 3: Implement Heartbeat**

Append to `morning_digest/progress.py`:
```python
class Heartbeat:
    """Daemon that logs the in-flight set every interval_s seconds."""

    def __init__(self, interval_s: float = 15.0):
        self.interval_s = interval_s
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self.interval_s <= 0:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            line = heartbeat_line()
            if line:
                log.info(line)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
```

- [ ] **Step 4: Run to verify passes**

Run: `pytest tests/test_progress.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add morning_digest/progress.py tests/test_progress.py
git commit -m "feat(progress): heartbeat daemon"
```

---

## Task 6: Wire progress into call_llm + run loop + desk pool

**Files:**
- Modify: `morning_digest/llm.py`, `pipeline.py`, `stages/analyze_domain.py`
- Test: `tests/test_llm.py`, `tests/test_pr0_instrumentation.py`

- [ ] **Step 1: Write failing test — call_llm wraps the provider call in track()**

`tests/test_pr0_instrumentation.py`:
```python
import logging
from unittest.mock import MagicMock, patch
from morning_digest.llm import call_llm


@patch("morning_digest.llm._fireworks_client")
def test_call_llm_emits_progress(mock_client, caplog):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = '{"ok": 1}'
    resp.usage.prompt_tokens = 5
    resp.usage.completion_tokens = 2
    mock_client.return_value.chat.completions.create.return_value = resp
    with caplog.at_level(logging.INFO):
        call_llm("s", "u", {"provider": "fireworks", "model": "m", "max_tokens": 100,
                            "_obs": {"stage": "seams"}}, stream=False)
    msgs = " ".join(r.message for r in caplog.records)
    assert "seams" in msgs and "m" in msgs
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pr0_instrumentation.py::test_call_llm_emits_progress -v`
Expected: FAIL — no "seams" label in logs.

- [ ] **Step 3: Wrap the provider call in call_llm**

In `morning_digest/llm.py`, import progress and wrap the dispatch in `call_llm`:
```python
from morning_digest import progress
```
Replace the body of `call_llm` after `provider = ...`:
```python
    # Observability context rides in a single namespaced, read-only key set by the
    # runner. It is never popped or splatted into a provider call (call_llm builds
    # create_kwargs explicitly), so it cannot leak into the SDK. We deliberately do
    # NOT use three scattered _stage_name/_sublabel/_capture keys (landmine if a
    # future caller does client.create(**model_config)); and not contextvars,
    # because propagating them into analyze_domain's desk ThreadPoolExecutor costs
    # more machinery than this single-user batch warrants.
    obs = model_config.get("_obs") or {}
    stage = obs.get("stage", "llm")
    sublabel = obs.get("sublabel")
    model = model_config.get("model", "?")
    label = f"{stage}:{sublabel} {model}" if sublabel else f"{stage} {model}"
    with progress.track(label):
        if provider == "anthropic":
            return _call_anthropic(system_prompt, user_content, model_config, max_retries, json_mode, stream)
        return _call_fireworks(system_prompt, user_content, model_config, max_retries, json_mode, stream)
```
Remove the now-redundant `log.info(f"Calling LLM ({model})...")` in `_retry_loop` (the track() start line replaces it).

- [ ] **Step 4: Run to verify passes**

Run: `pytest tests/test_pr0_instrumentation.py::test_call_llm_emits_progress -v`
Expected: PASS.

- [ ] **Step 5: Add stage banner N/M and heartbeat lifecycle in the run loop**

In `pipeline.py` `run_pipeline`, before the stage loop:
```python
    from morning_digest import progress
    progress.reset()
    hb_interval = config.get("pipeline", {}).get("heartbeat_interval_s", 15)
    heartbeat = progress.Heartbeat(interval_s=hb_interval)
    heartbeat.start()
    total_stages = len(stage_manifest)
```
Wrap the loop body in `try/finally` so `heartbeat.stop()` always runs (place `heartbeat.stop()` in a `finally` around the `for` loop and finalization). Change the stage banner (line 731):
```python
        log.info(f"--- Stage {stage_idx}/{total_stages}: {stage_name} ---")
```
where `stage_idx` is `enumerate(stage_manifest, 1)`. Update the loop to `for stage_idx, stage_cfg in enumerate(stage_manifest, 1):`.

- [ ] **Step 6: Seed the `_obs` context into model_config per stage**

In the loop, after `model_config = _get_stage_model_config(...)` (line 696):
```python
        if isinstance(model_config, dict):
            model_config = {**model_config, "_obs": {"stage": stage_name}}
```
(Task 11 extends this `_obs` dict with `capture_dir` when `--capture-prompts` is set.)

- [ ] **Step 7: Add per-desk track() in analyze_domain**

In `stages/analyze_domain.py`, the per-desk worker that calls `call_llm` (around line 674): wrap the desk work in `progress.track(f"desk {domain_key}")` and merge `sublabel` into `_obs`:
```python
    from morning_digest import progress
    with progress.track(f"desk {domain_key}"):
        # Merge sublabel into the runner-seeded _obs so the LLM line is attributed
        # to the desk while preserving stage/capture_dir.
        base = model_config or {}
        mc = {**base, "_obs": {**(base.get("_obs") or {}), "sublabel": domain_key}}
        result, _usage = call_llm(system_prompt, user_content, mc, ...)
```
(Use the actual desk-key variable name in scope; `domain_key` per `_DOMAIN_CONFIGS`.)

- [ ] **Step 8: Run suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add morning_digest/llm.py pipeline.py stages/analyze_domain.py tests/test_pr0_instrumentation.py
git commit -m "feat(progress): wire live progress + heartbeat into pipeline"
```

---

## Task 7: metrics.py — aggregate_usage

**Files:**
- Create: `morning_digest/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write failing test**

`tests/test_metrics.py`:
```python
from morning_digest.metrics import aggregate_usage
from morning_digest.llm import LLMUsage


def test_aggregate_usage_sums_and_counts_missing():
    records = [
        LLMUsage("m1", "fireworks", 100, 40, 30),
        LLMUsage("m1", "fireworks", 50, 10, 0),
        LLMUsage("m2", "fireworks", None, None, None),
    ]
    agg = aggregate_usage(records)
    assert agg["tokens_in"] == 150
    assert agg["tokens_out"] == 50
    assert agg["tokens_cached"] == 30
    assert agg["usage_missing"] == 1
    assert agg["model"] == "m1"  # dominant by call count


def test_aggregate_usage_empty():
    agg = aggregate_usage([])
    assert agg == {"model": None, "tokens_in": 0, "tokens_out": 0,
                   "tokens_cached": 0, "usage_missing": 0}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement metrics.py**

```python
"""Pure metric aggregation helpers. No I/O, no global state."""
from __future__ import annotations

from collections import Counter

from morning_digest.llm import LLMUsage


def aggregate_usage(records: list[LLMUsage]) -> dict:
    if not records:
        return {"model": None, "tokens_in": 0, "tokens_out": 0,
                "tokens_cached": 0, "usage_missing": 0}
    tokens_in = sum(r.tokens_in or 0 for r in records)
    tokens_out = sum(r.tokens_out or 0 for r in records)
    tokens_cached = sum(r.tokens_cached or 0 for r in records)
    missing = sum(1 for r in records if r.tokens_in is None or r.tokens_out is None)
    dominant = Counter(r.model for r in records).most_common(1)[0][0]
    return {
        "model": dominant,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_cached": tokens_cached,
        "usage_missing": missing,
    }
```

- [ ] **Step 4: Run to verify passes**

Run: `pytest tests/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add morning_digest/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): aggregate_usage helper"
```

---

## Task 8: Stages surface llm_usage; runner folds into run_meta.metrics

**Files:**
- Modify: stage modules (collect usage), `pipeline.py` (fold), `_run_with_retry`
- Test: `tests/test_pr0_instrumentation.py`

- [ ] **Step 1: Write failing test — runner folds llm_usage into run_meta**

```python
from morning_digest.metrics import aggregate_usage
import pipeline


def test_runner_folds_llm_usage(monkeypatch, tmp_path):
    # A fake stage returns llm_usage; assert it lands in run_meta.metrics and
    # is NOT written as a stray artifact.
    from morning_digest.llm import LLMUsage
    fake_outputs = {"foo": [1, 2, 3], "llm_usage": [LLMUsage("m", "fireworks", 100, 20)]}
    folded = pipeline._fold_stage_metrics(
        run_meta={"metrics": {"stages": {}, "overrides": {}, "totals": {}}},
        stage_name="seams",
        outputs=dict(fake_outputs),
        latency_s=1.2,
        retries=0,
    )
    assert "llm_usage" not in folded  # popped
    # run_meta updated in place; check via return of remaining outputs
```

(Adjust to the real `_fold_stage_metrics` signature defined in Step 3.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pr0_instrumentation.py::test_runner_folds_llm_usage -v`
Expected: FAIL — `_fold_stage_metrics` missing.

- [ ] **Step 3: Add `_fold_stage_metrics` to pipeline.py**

```python
from morning_digest.metrics import aggregate_usage

_RESERVED_METRIC_KEYS = ("llm_usage", "override_counts", "domain_research_metrics")


def _fold_stage_metrics(run_meta, stage_name, outputs, latency_s, retries):
    """Pop reserved metric keys from outputs and fold into run_meta['metrics']."""
    metrics = run_meta.setdefault("metrics", {"stages": {}, "overrides": {}, "totals": {}})
    usage = outputs.pop("llm_usage", []) or []
    agg = aggregate_usage(list(usage))
    stage_metrics = {
        "model": agg["model"],
        "tokens_in": agg["tokens_in"],
        "tokens_out": agg["tokens_out"],
        "tokens_cached": agg["tokens_cached"],
        "usage_missing": agg["usage_missing"],
        "latency_s": latency_s,
        "retries": retries,
    }
    metrics["stages"][stage_name] = stage_metrics
    overrides = outputs.pop("override_counts", {}) or {}
    for k, v in overrides.items():
        metrics["overrides"][k] = metrics["overrides"].get(k, 0) + v
    dr = outputs.pop("domain_research_metrics", None)
    if dr is not None:
        metrics["domain_research"] = dr
    totals = metrics["totals"]
    for key in ("tokens_in", "tokens_out", "tokens_cached", "usage_missing"):
        totals[key] = totals.get(key, 0) + agg[key]
    return outputs
```

Initialize `run_meta["metrics"] = {"stages": {}, "overrides": {}, "totals": {}}` where `run_meta` is built (line 676 block).

- [ ] **Step 4: Call the fold in the run loop, before the artifact-save loop**

Replace the section after `elapsed = ...; run_meta["stage_timings"][stage_name] = ...` and `context.update(outputs)`:
```python
        context.update(outputs)
        outputs = _fold_stage_metrics(
            run_meta, stage_name, outputs, latency_s=round(elapsed, 2), retries=_last_attempts - 1
        )
        _log_stage_observability(stage_name, outputs)
        for key, value in outputs.items():
            if key not in ("html",):
                _save_artifact(artifact_dir, key, value)
```
Note: `context.update(outputs)` runs BEFORE the pop so downstream stages still see real outputs; the reserved keys are harmless in context. The pop only affects what gets saved/observed.

- [ ] **Step 5: Make `_run_with_retry` report attempts**

Change `_run_with_retry` to return `(result, attempts)`:
```python
def _run_with_retry(fn, stage_name, max_retries=2, backoff_base_seconds=5):
    for attempt in range(max_retries + 1):
        try:
            return fn(), attempt + 1
        except Exception as e:
            if attempt < max_retries:
                wait = 2 ** (attempt + 1) * backoff_base_seconds
                log.warning(f"Stage '{stage_name}' failed (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {wait}s")
                time.sleep(wait)
            else:
                raise
```
At the call site (line 737): `outputs, _last_attempts = _run_with_retry(...)`. In the `except` path, set `_last_attempts = max_retries + 1` before folding (the failure path uses `_empty_stage_output`; still fold with its empty outputs so the stage appears in metrics with retries recorded).

- [ ] **Step 6: Surface llm_usage from each LLM stage**

For each stage, collect the `_usage` values (renamed from the `_` discards in Task 2) into a list and add to the returned outputs dict under `"llm_usage"`. Examples:

`stages/compress.py` — single call: keep the usage and include it:
```python
        compressed, usage = call_llm(...)
        ...
        return {..., "llm_usage": [usage]}
```
`cross_domain/stage.py` `run()` — collect both turns:
```python
    usages = []
    ...
    cross_domain_plan, u = _call_turn_json(...); usages.append(u)
    ...
    result, u = _call_turn_json(...); usages.append(u)
    ...
    return {..., "llm_usage": usages}   # add to the existing return dict
```
`stages/analyze_domain.py` — each desk worker returns its usage; `_run_all_domains` aggregates the per-desk usages into a list returned under `llm_usage` in the stage outputs.
`stages/seams.py`, `stages/coverage_gaps.py`, `stages/prepare_spiritual_weekly.py`, `stages/enrich_articles/canonical.py` (its caller stage) — same pattern: accumulate `usage` objects, return `"llm_usage": [...]`.

- [ ] **Step 7: Add REAL behavioral guards (not a source grep)**

A string grep proves nothing (passes on a comment). Instead, assert that a stage actually *returns* populated `llm_usage`. Add a real test for the multi-call stage in `tests/test_cross_domain.py` (it has a well-understood input shape):

```python
from cross_domain import stage as xd_stage
from morning_digest.llm import LLMUsage


@patch("cross_domain.stage.call_llm")
def test_cross_domain_surfaces_llm_usage(mock_llm):
    mock_llm.side_effect = [
        llm_result({"deep_dives": [], "worth_reading": [], "cross_domain_connections": []},
                   tokens_in=900, tokens_out=120),   # plan turn
        llm_result({"at_a_glance": [], "deep_dives": [], "worth_reading": [],
                    "cross_domain_connections": []}, tokens_in=1500, tokens_out=300),  # execute turn
    ]
    ctx = {"domain_analysis": {"econ": {"items": [{"item_id": "e1", "headline": "h"}]}},
           "seam_data": {}, "raw_sources": {"rss": []}}
    outputs = xd_stage.run(ctx, {"digest": {}, "cross_domain": {}}, {"provider": "fireworks", "model": "m"})
    usage = outputs["llm_usage"]
    assert len(usage) == 2 and all(isinstance(u, LLMUsage) for u in usage)
    assert usage[0].tokens_in == 900 and usage[1].tokens_out == 300
```

Then, as part of Task 8 Step 6, add **one line** to an existing happy-path test in each remaining LLM stage's test file — these tests already build valid context and mock `call_llm`, so the assertion is real, not static:
- `tests/test_compress.py`: in the successful-run test, `assert outputs["llm_usage"]`.
- `tests/test_coverage_gaps.py`: same.
- `tests/test_seams.py`: in a successful per-item/annotation run test, `assert outputs["llm_usage"]`.
- `tests/test_analyze_domain.py`: in a successful desk-run test, `assert outputs["llm_usage"]` (one entry per desk that ran).
- `tests/test_prepare_spiritual_weekly.py`: same.

This guards the contract behaviorally: a stage that adds an LLM call but forgets to surface usage fails a real assertion on real output.

- [ ] **Step 8: Run suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pipeline.py stages/ cross_domain/ tests/test_pr0_instrumentation.py
git commit -m "feat(metrics): per-stage LLM usage folded into run_meta.metrics"
```

---

## Task 8.5: Golden characterization test for `_validated_output` (do BEFORE Task 9)

Task 9 rewrites the tag/tag_label loop inside `_validated_output` to add counting. PR-0 promises "no behavior change," so we pin the current output *before* touching it. This golden test captures today's behavior; Task 9 must keep it green.

**Files:**
- Create: `tests/golden/cross_domain_validated.json` (captured fixture)
- Test: `tests/test_cross_domain.py`

- [ ] **Step 1: Add the test with a representative input that exercises the overrides**

```python
import json
from pathlib import Path
from cross_domain.parse import _validated_output

# Input chosen to trigger every override: off-vocab tag ("AI"), a
# widely-reported claim backed by a single domain (source_depth recompute),
# and a deep dive. Keep this STATIC — it is the characterization input.
_GOLDEN_INPUT = {
    "at_a_glance": [
        {"item_id": "g1", "tag": "AI", "tag_label": "bogus",
         "source_depth": "widely-reported", "headline": "h1",
         "facts": "f", "analysis": "a",
         "links": [{"url": "https://reuters.com/x"}]},
    ],
    "deep_dives": [
        {"headline": "Deep one", "source_depth": "corroborated", "body": "b",
         "further_reading": [{"url": "https://apnews.com/y"}]},
    ],
    "cross_domain_connections": [],
    "worth_reading": [],
}
_GOLDEN_DOMAIN_ANALYSIS = {"econ": {"market_context": "ctx"}}
_GOLDEN_RAW = {"rss": [{"url": "https://reuters.com/x"}, {"url": "https://apnews.com/y"}]}
_GOLDEN_CONFIG = {"digest": {"at_a_glance": {"max_items": 7}}}

_GOLDEN_PATH = Path(__file__).parent / "golden" / "cross_domain_validated.json"


def _strip_internal(result: dict) -> dict:
    out = json.loads(json.dumps(result))  # deep copy + JSON-normalize
    out.pop("_override_counts", None)
    out.pop("_source_depth_downgrades", None)
    return out


def test_validated_output_matches_golden():
    import copy
    result = _validated_output(
        copy.deepcopy(_GOLDEN_INPUT),
        _GOLDEN_DOMAIN_ANALYSIS, _GOLDEN_RAW, _GOLDEN_CONFIG,
    )
    golden = json.loads(_GOLDEN_PATH.read_text())
    assert _strip_internal(result) == golden
```

- [ ] **Step 2: Capture the golden by running the test once in "record" mode**

Run this one-off snippet (not committed) to write the golden file from current behavior:
```bash
mkdir -p tests/golden
python -c "
import json, copy
from tests.test_cross_domain import _GOLDEN_INPUT, _GOLDEN_DOMAIN_ANALYSIS, _GOLDEN_RAW, _GOLDEN_CONFIG, _strip_internal
from cross_domain.parse import _validated_output
r = _validated_output(copy.deepcopy(_GOLDEN_INPUT), _GOLDEN_DOMAIN_ANALYSIS, _GOLDEN_RAW, _GOLDEN_CONFIG)
open('tests/golden/cross_domain_validated.json','w').write(json.dumps(_strip_internal(r), indent=2, sort_keys=True))
print('golden captured')
"
```
Expected: prints `golden captured`; `tests/golden/cross_domain_validated.json` now holds current `_validated_output` output (tag normalized `AI`→`ai`, source_depth recomputed to `single-source`, etc.).

- [ ] **Step 3: Run the test to verify it passes against the just-captured golden**

Run: `pytest tests/test_cross_domain.py::test_validated_output_matches_golden -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/golden/cross_domain_validated.json tests/test_cross_domain.py
git commit -m "test: golden characterization for _validated_output (pre-refactor)"
```

After Task 9's refactor, this test must still pass unchanged. If it fails, the "observe-only" promise is broken — inspect the diff and fix the refactor (not the golden).

---

## Task 9: Override-firing counts

**Files:**
- Modify: `cross_domain/parse.py`, `cross_domain/stage.py`, `stages/analyze_domain.py`
- Test: `tests/test_cross_domain.py`, `tests/test_analyze_domain.py`, `tests/test_pr0_instrumentation.py`

- [ ] **Step 1: Write failing test — _validated_output reports override_counts**

In `tests/test_cross_domain.py`:
```python
from cross_domain.parse import _validated_output

def test_validated_output_counts_overrides():
    result = {
        "at_a_glance": [
            {"item_id": "a", "tag": "AI", "tag_label": "wrong", "source_depth": "widely-reported",
             "links": [{"url": "https://x.com/1"}]},
        ],
        "deep_dives": [], "cross_domain_connections": [], "worth_reading": [],
    }
    counts = result.setdefault("_override_counts", {})
    out = _validated_output(result, {}, {}, {"digest": {}})
    oc = out["_override_counts"]
    assert oc["normalize_tag"] >= 1        # "AI" -> "ai"
    assert oc["recompute_source_depth"] >= 1  # widely-reported single domain -> downgraded
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_cross_domain.py::test_validated_output_counts_overrides -v`
Expected: FAIL — `_override_counts` not produced.

- [ ] **Step 3: Tally overrides in _validated_output**

In `cross_domain/parse.py` `_validated_output`, build a counts dict:
```python
    counts = result.setdefault("_override_counts", {
        "normalize_tag": 0, "tag_label": 0, "recompute_source_depth": 0,
        "ensure_primary_glance_coverage": 0, "overlap_downgrade": 0,
    })
    for item in result["at_a_glance"]:
        raw_tag = item.get("tag", "")
        norm = _normalize_tag(raw_tag)
        if norm != raw_tag:
            counts["normalize_tag"] += 1
        item["tag"] = norm
        new_label = _TAG_LABELS.get(item["tag"], item.get("tag_label", ""))
        if new_label != item.get("tag_label", ""):
            counts["tag_label"] += 1
        item["tag_label"] = new_label
```
After `_ensure_primary_glance_coverage` (line 612), count additions:
```python
    before = len(result["at_a_glance"])
    result["at_a_glance"] = _ensure_primary_glance_coverage(result["at_a_glance"], domain_analysis, config)
    counts["ensure_primary_glance_coverage"] += len(result["at_a_glance"]) - before
```
After `_downgrade_same_outlet_depth`/`_downgrade_overlap_depth` (line 632-633), derive the counts from the existing downgrades list — but **filter by reason**. Both passes append to `_source_depth_downgrades`; the phrase-overlap pass tags its entries with `reason == "phrase_overlap_with_at_a_glance"`, the same-outlet recompute pass adds no `reason`. Counting the whole list would conflate two distinct overrides:
```python
    downgrades = result.get("_source_depth_downgrades", [])
    counts["recompute_source_depth"] += sum(
        1 for d in downgrades if d.get("reason") != "phrase_overlap_with_at_a_glance"
    )
    counts["overlap_downgrade"] = counts.get("overlap_downgrade", 0) + sum(
        1 for d in downgrades if d.get("reason") == "phrase_overlap_with_at_a_glance"
    )
```
(`overlap_downgrade` is a sixth override outside PR-A's named five, but it's a real one — counting it separately keeps the recompute_source_depth evidence clean for PR-A's keep/delete call and surfaces overlap-downgrade activity honestly.) Add `"overlap_downgrade": 0` to the initial `counts` dict.

- [ ] **Step 4: Surface override_counts from the cross_domain stage**

In `cross_domain/stage.py`, where `_validated_output` result is returned as outputs, lift `result.pop("_override_counts", {})` into the stage outputs as `"override_counts"` (merge with any analyze-side counts is done by the runner). Also strip the internal `_source_depth_downgrades`/`_override_counts` from the saved artifact as today.

- [ ] **Step 5: Count _rebalance_categories in analyze_domain**

`_rebalance_categories` returns `(domain_analysis[desk], rebalance_log)` (line 901). Sum synthesized-item counts across desks into `override_counts["rebalance_categories"]` and include in the analyze_domain stage outputs under `"override_counts"`.

- [ ] **Step 6: Write failing test — runner folds override_counts**

```python
def test_runner_folds_override_counts():
    rm = {"metrics": {"stages": {}, "overrides": {}, "totals": {}}}
    pipeline._fold_stage_metrics(rm, "cross_domain",
        {"override_counts": {"normalize_tag": 3}}, latency_s=0.1, retries=0)
    pipeline._fold_stage_metrics(rm, "analyze_domain",
        {"override_counts": {"rebalance_categories": 2, "normalize_tag": 1}}, latency_s=0.1, retries=0)
    assert rm["metrics"]["overrides"] == {"normalize_tag": 4, "rebalance_categories": 2}
```

(The fold logic from Task 8 Step 3 already accumulates `override_counts`; this test just locks it in.)

- [ ] **Step 7: Run suite — golden test MUST still pass**

Run: `pytest tests/test_cross_domain.py::test_validated_output_matches_golden -v && pytest -q`
Expected: PASS. The golden test is the proof that rewriting the tag/tag_label loop did not change behavior. If it fails, inspect the diff and fix the refactor — do **not** regenerate the golden.

- [ ] **Step 8: Commit**

```bash
git add cross_domain/ stages/analyze_domain.py tests/
git commit -m "feat(metrics): count override firings (all five)"
```

---

## Task 10: Generic item-flow + domain_research metrics

**Files:**
- Modify: `pipeline.py`, `stages/analyze_domain.py`
- Test: `tests/test_pr0_instrumentation.py`

- [ ] **Step 1: Write failing test for generic items_out**

```python
def test_fold_records_items_out():
    rm = {"metrics": {"stages": {}, "overrides": {}, "totals": {}}}
    pipeline._fold_stage_metrics(rm, "collect",
        {"raw_sources": {"rss": [1, 2, 3]}, "extra": [9]}, latency_s=0.1, retries=0)
    items_out = rm["metrics"]["stages"]["collect"]["items_out"]
    assert items_out["extra"] == 1
    assert items_out.get("raw_sources.rss") == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pr0_instrumentation.py::test_fold_records_items_out -v`
Expected: FAIL — no `items_out`.

- [ ] **Step 3: Add generic item-flow in _fold_stage_metrics**

In `_fold_stage_metrics`, after building `stage_metrics`, before returning:
```python
    items_out = {}
    for key, value in outputs.items():
        if isinstance(value, list):
            items_out[key] = len(value)
        elif isinstance(value, dict):
            for sub, subval in value.items():
                if isinstance(subval, list):
                    items_out[f"{key}.{sub}"] = len(subval)
    stage_metrics["items_out"] = items_out
```
(`# TODO: add items_in best-effort per spec Component 4 once a per-stage need is concrete.` — leave items_in unimplemented for now per the spec's best-effort note and the "mark speculative keys with a TODO" guidance.)

- [ ] **Step 4: Surface domain_research_metrics**

In `stages/analyze_domain.py` `_run_domain_research` (or its caller), record `{"fired": <int>, "articles_fetched": <int>, "changed_output": <bool>}` and add to the stage outputs as `"domain_research_metrics"`. The fold in Task 8 already routes this key to `metrics.domain_research`.

- [ ] **Step 5: Add a test for domain_research routing**

```python
def test_fold_routes_domain_research():
    rm = {"metrics": {"stages": {}, "overrides": {}, "totals": {}}}
    pipeline._fold_stage_metrics(rm, "analyze_domain",
        {"domain_research_metrics": {"fired": 2, "articles_fetched": 7, "changed_output": True}},
        latency_s=0.1, retries=0)
    assert rm["metrics"]["domain_research"] == {"fired": 2, "articles_fetched": 7, "changed_output": True}
```

- [ ] **Step 6: Run suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pipeline.py stages/analyze_domain.py tests/test_pr0_instrumentation.py
git commit -m "feat(metrics): generic item-flow + domain_research metrics"
```

---

## Task 11: --capture-prompts flag + prompt dump

**Files:**
- Modify: `morning_digest/llm.py`, `pipeline.py`
- Test: `tests/test_pr0_instrumentation.py`

- [ ] **Step 1: Write failing test — capture writes the exact prompt**

```python
@patch("morning_digest.llm._fireworks_client")
def test_capture_prompts_writes_files(mock_client, tmp_path):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "{}"
    resp.usage.prompt_tokens = 1
    resp.usage.completion_tokens = 1
    mock_client.return_value.chat.completions.create.return_value = resp
    mc = {"provider": "fireworks", "model": "m", "max_tokens": 100,
          "_obs": {"stage": "seams", "capture_dir": str(tmp_path)}}
    call_llm("SYSTEM-XYZ", "USER-ABC", mc, stream=False)
    call_llm("SYSTEM-2", "USER-2", mc, stream=False)  # second call → per-stage seq 02
    files = sorted(p.name for p in tmp_path.glob("seams__*.txt"))
    assert files == ["seams__01.txt", "seams__02.txt"]   # per-stage counter, not global
    content = (tmp_path / "seams__01.txt").read_text()
    assert "SYSTEM-XYZ" in content and "USER-ABC" in content
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_pr0_instrumentation.py::test_capture_prompts_writes_files -v`
Expected: FAIL — no files written.

- [ ] **Step 3: Implement capture in call_llm**

In `call_llm`, inside the `with progress.track(label):` block, before dispatch (note `obs`/`stage` are already in scope from Task 6 Step 3):
```python
        capture_dir = obs.get("capture_dir")
        if capture_dir:
            _capture_prompt(capture_dir, stage, system_prompt, user_content)
```
Add the writer with a **per-stage, filesystem-derived** sequence — no global counter, no reset, deterministic per stage:
```python
from pathlib import Path


def _capture_prompt(capture_dir: str, stage: str, system_prompt: str, user_content: str) -> None:
    d = Path(capture_dir)
    d.mkdir(parents=True, exist_ok=True)
    # Per-stage sequence from existing files on disk — a global itertools counter
    # would number across stages (seams__03.txt for the 1st seams call) and make
    # the PR-B baseline diff non-deterministic. Deriving from disk is stateless.
    n = len(list(d.glob(f"{stage}__*.txt"))) + 1
    (d / f"{stage}__{n:02d}.txt").write_text(
        f"=== SYSTEM ===\n{system_prompt}\n\n=== USER ===\n{user_content}\n",
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run to verify passes**

Run: `pytest tests/test_pr0_instrumentation.py::test_capture_prompts_writes_files -v`
Expected: PASS.

- [ ] **Step 5: Add the CLI flag and thread the capture dir**

In `pipeline.py` `main()` add:
```python
    parser.add_argument("--capture-prompts", type=str, default=None,
                        help="Dump exact rendered prompts per stage to this dir (PR-B baseline)")
```
Pass `capture_prompts` into `run_pipeline(...)` (add the param, default `None`). Replace the `_obs` seeding from Task 6 Step 6 so it also carries the capture dir:
```python
        if isinstance(model_config, dict):
            obs = {"stage": stage_name}
            if capture_prompts:
                obs["capture_dir"] = capture_prompts
            model_config = {**model_config, "_obs": obs}
```

- [ ] **Step 6: Run suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add morning_digest/llm.py pipeline.py tests/test_pr0_instrumentation.py
git commit -m "feat(observability): --capture-prompts flag dumps exact prompts"
```

---

## Task 12: Capture the PR-B baseline (closing step)

**Files:**
- Create: `output/prompt_baseline/` (committed fixture), `docs/prompt-baseline-README.md`

- [ ] **Step 1: Pick a frozen upstream artifact day**

Run: `ls output/artifacts/ | tail -5`
Choose a recent dated dir with `raw_sources.json` + `domain_analysis.json` present. Record the date (call it `$D`).

- [ ] **Step 2: Capture prompts against the frozen fixture**

Run (from the repo root, env vars set; LLM calls happen but only prompt assembly matters):
```bash
python pipeline.py --stage cross_domain --dry-run --capture-prompts output/prompt_baseline/
python pipeline.py --stage seams --dry-run --capture-prompts output/prompt_baseline/
```
Expected: `output/prompt_baseline/cross_domain__*.txt`, `seams__*.txt` written.

If running real LLM calls is undesirable for the baseline, instead capture via a mocked harness script that calls each stage's prompt-builder with the loaded `$D` artifacts and writes the same files — the prompt *text* is what matters, not the responses.

- [ ] **Step 3: Document and commit the baseline**

Write `docs/prompt-baseline-README.md`:
```markdown
# PR-B prompt baseline

Captured at end of PR-0 from artifact day `$D` via
`python pipeline.py --stage <s> --dry-run --capture-prompts output/prompt_baseline/`.
PR-B re-runs the identical command and diffs against these files; with
audience.yaml populated to today's values, the rendered prompts must be
byte-identical. Any delta is a threading bug.
```

```bash
git add output/prompt_baseline/ docs/prompt-baseline-README.md
git commit -m "chore: capture PR-B prompt baseline"
```

- [ ] **Step 4: Final full-suite run**

Run: `pytest -q`
Expected: PASS, no skips introduced by PR-0.

---

## Verification (whole PR-0)

- [ ] `pytest -q` green.
- [ ] A real `python pipeline.py --dry-run` (or `--stage <late_stage>` off cached artifacts) shows: `--- Stage N/M: name ---` banners, per-LLM-call `start`/`done Xs` lines, `[hb] waiting on …` ticks during long waits, and writes `run_meta.json` containing a populated `metrics` block (`stages`, `overrides`, `totals`, and `domain_research` if analyze_domain ran).
- [ ] No pipeline behavior changed: at_a_glance/deep_dives/seam outputs match pre-PR-0 for the same inputs (the overrides still fire identically — PR-0 only counts them).
- [ ] `run_meta.json` has no stray `llm_usage`/`override_counts`/`domain_research_metrics` top-level artifacts in the artifact dir.
