# Agent Guidelines

## Testing

Dependencies (yt-dlp, feedparser, anthropic, etc.) are only installed inside the Docker container. Always rebuild and run tests there:

```bash
docker compose build
docker compose run --rm --no-deps morning-digest python -m pytest tests/ -v --tb=short
```

The test suite includes a ruff lint check (`tests/test_lint.py`). If ruff fails, fix the lint issues before committing.

## Stage contracts

Each pipeline stage consumes keys from `context` and produces new keys. When changing the output schema of any stage (field names, value types, dict structure), check every downstream consumer — the next stage, `stages/assemble.py`, and `templates/email_template.py`. The tag vocabulary (`war`, `ai`, `domestic`, `defense`, `space`, `tech`, `local`, `science`, `econ`, `cyber`) is defined independently in `validate.py`, `stages/cross_domain.py`, `stages/assemble.py`, and the template CSS — all four must stay in sync.
