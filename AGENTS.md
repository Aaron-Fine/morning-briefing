# Agent Guidelines

## Testing

Dependencies (yt-dlp, feedparser, anthropic, etc.) are only installed inside the Docker container. Always rebuild and run tests there:

```bash
docker compose build
docker compose run --rm --no-deps morning-digest python -m pytest tests/ -v --tb=short
```

The test suite includes a ruff lint check (`tests/test_lint.py`). If ruff fails, fix the lint issues before committing.

## Stage contracts

Each pipeline stage consumes keys from `context` and produces new keys. When changing the output schema of any stage (field names, value types, dict structure), check every downstream consumer — the next stage, `stages/assemble.py`, and `templates/email_template.py`.

### Tag vocabulary

Tags: `war`, `ai`, `domestic`, `defense`, `space`, `tech`, `local`, `science`, `econ`, `cyber`, `energy`, `biotech`. These are defined in 5 synchronized surfaces — all must stay in sync:

1. `morning_digest/validate.py` — `VALID_TAGS` and `VALID_TAG_LABELS`
2. `stages/cross_domain.py` — `_VALID_TAGS`, `_TAG_LABELS`, and `_TAG_KEYWORDS`
3. `stages/assemble.py` — `_TAG_LABELS`
4. `templates/email_template.py` — CSS `--tag-*-text` / `--tag-*-bg` variables
5. `prompts/cross_domain_execute.md` — tag list in the output schema

Contract tests in `tests/test_contracts.py` verify consistency across all surfaces.

### Desk manifest

Seven analysis desks are configured in `config.yaml` under `desks:` and implemented in `stages/analyze_domain.py` (`_DOMAIN_CONFIGS`). Each desk maps RSS feed categories to a specialist analysis pass. Desks run in parallel via `ThreadPoolExecutor`.

### Two-turn stages

`seams` and `cross_domain` use a two-turn LLM pattern (scan → synthesis and plan → execute respectively). Per-turn model overrides are configured in `config.yaml` under `turns.<turn_name>`.

### Coverage gaps

`stages/coverage_gaps.py` is a diagnostic stage that runs after `cross_domain`. It identifies blind spots in source coverage and appends to `output/coverage_gaps_history.jsonl` for recurring pattern detection. Output is artifacts-only — it never appears in the sent email.
