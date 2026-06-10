# Agent Guidelines

## Docker / Pipeline

Never run `pipeline.py` directly on the host. All pipeline execution must happen inside Docker — dependencies (yt-dlp, feedparser, anthropic, etc.) exist only in the container image.

## Commit Policy

- Commit after completing each feature or logical unit of work. Do not accumulate unrelated changes in a single commit.
- Always commit at the end of your turn if there are staged or modified tracked files.
- Stage new files explicitly (`git add <file>`). Never use `git add -A` or `git add .` — risks committing secrets or large binaries.
- Write commit messages that explain *why*, not just *what*.

## Push Policy

- Push at least once per batch of features, or at the end of a work session.
- Do not push mid-feature if the code is in a broken or partial state.

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

Tags: `war`, `ai`, `domestic`, `defense`, `space`, `tech`, `local`, `science`, `econ`, `cyber`, `energy`, `biotech`. The **canonical definition** lives in `morning_digest/tags.py` (`TAG_LABELS`, `VALID_TAGS`, and `label_for_tag` to derive a tag's display label). Everything else derives from it or must stay consistent with it:

1. `morning_digest/tags.py` — canonical `TAG_LABELS` / `VALID_TAGS` / `label_for_tag`
2. `morning_digest/validate.py` and `stages/cross_domain.py` — re-export the canonical names for back-compat; do not redefine the vocabulary here
3. `stages/assemble.py` — derives each item's `tag_label` via `label_for_tag` (no local map)
4. `templates/email_template.py` — CSS `--tag-*-text` / `--tag-*-bg` variables must cover every tag
5. `stages/analyze_domain.py` — `_DOMAIN_CONFIGS[*]["tags"]` per-desk allowed-tag strings: cross_domain derives each at-a-glance item's `tag` from its desk-of-origin, so the desk configs are where item tags originate (the execute prompt no longer asks the LLM for a tag)

Contract tests in `tests/test_contracts.py` verify consistency across these surfaces.

### Desk manifest

Seven analysis desks are configured in `config/pipeline.yaml` under `desks:` and implemented in `stages/analyze_domain.py` (`_DOMAIN_CONFIGS`). Each desk maps RSS feed categories to a specialist analysis pass. Desks run in parallel via `ThreadPoolExecutor`.

### Two-turn stages

`seams` and `cross_domain` use a two-turn LLM pattern (scan → synthesis and plan → execute respectively). Per-turn model overrides are configured in `config/pipeline.yaml` under `pipeline.stages[].turns.<turn_name>`.

## Article Enrichment

- `enrich_articles` normalizes RSS items to canonical sanitized summaries.
- Enrichment budgets are **tiered by source health**: `enrichment_required` feeds get uncapped fetches + browser-fetch fallback; `active`/`low_frequency` share the standard cap; `headline_radar`/`degraded`/`broken` are never fetched. See `config/pipeline.yaml` under `enrich_articles.tier_caps`.
- Inspect `output/artifacts/YYYY-MM-DD/enrich_articles.json` for per-item provenance, status, tier, and before/after lengths.
- Use `scripts/audit_rss_quality.py` to measure feed quality and tune `rss.feeds[].enrich.strategy`.
- Use `scripts/source_health.py` to inspect per-feed `source_health.json` artifacts and monitor status transitions.
- Cookie files for authenticated fetches live in `cookies/` and must not be committed.
