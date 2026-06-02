# PR-B prompt baseline

This directory's sibling `output/prompt_baseline/` holds the **rendered-prompt
baseline** captured at the end of PR-0. PR-B (audience.yaml threading) re-runs the
identical frozen fixture and diffs its rendered prompts against this baseline:
with `config/audience.yaml` populated to today's values, the prompts must be
**byte-identical**. Any unintended delta is a threading bug.

## How it is captured

PR-0 added `--capture-prompts <dir>` to `pipeline.py`. When set, `call_llm` writes
the exact `system_prompt` + `user_content` it is about to send to
`<dir>/<stage>__<NN>.txt` (per-stage sequence, derived from files on disk so the
diff is deterministic). It is observe-only and writes the prompt *before* the
provider call.

## What was captured here

These files were captured during PR-0 against the frozen upstream artifacts in
`output/artifacts/baseline/` (`raw_sources.json`, `domain_analysis.json`,
`seam_data.json`), staged as a dated dir and run with real Fireworks calls
(`kimi-k2p6`):

```bash
python pipeline.py --stage seams --dry-run --capture-prompts output/prompt_baseline/
```

Because `seams` precedes `cross_domain` in the manifest, a single `--stage seams`
run captures both. Committed files:
- `seams__01.txt`
- `cross_domain__01.txt` (Turn 1, planning)
- `cross_domain__02.txt` (Turn 2, execution)

`output/` is gitignored, so these were added with `git add -f`.

## IMPORTANT — multi-turn determinism caveat

`cross_domain` is a **two-turn** stage: Turn 2's prompt is assembled from Turn 1's
LLM *response*. Turn-1 prompt assembly (and `seams`) is deterministic from the
frozen fixture, so `cross_domain__01.txt` and `seams__01.txt` are byte-reproducible
given the same inputs. `cross_domain__02.txt` depends on a (non-deterministic) LLM
response and is **not** byte-reproducible across runs by itself. PR-B should diff
the deterministic prompts (Turn 1 + single-turn stages), or pin a deterministic
Turn-1 response (temperature 0 / recorded fixture) before diffing Turn 2.

## Re-capturing / extending the baseline

Run in an environment with `FIREWORKS_API_KEY` / `ANTHROPIC_API_KEY` set and a
frozen upstream artifact day present, then `git add -f` the result:

```bash
python pipeline.py --stage seams --dry-run --capture-prompts output/prompt_baseline/
git add -f output/prompt_baseline/ && git add docs/prompt-baseline-README.md
git commit -m "chore: capture PR-B prompt baseline"
```

The `--capture-prompts` mechanism captures any stage that calls the LLM; add more
stages to the baseline by running from an earlier `--stage`.

## PR-B usage

PR-B re-runs the identical command against the same frozen fixture and diffs the
output against `output/prompt_baseline/`. Identical = threading is correct; any
delta = a bug in how audience values are threaded into prompt assembly.
