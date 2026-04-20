# RSS Article Enrichment — Design

**Date:** 2026-04-19
**Status:** Design approved, implementation pending

## Problem

Some RSS feeds arrive too thin for downstream analysis:

1. **`html_index`-scraped sources** (Brad Setser, Reuters Markets, China Global South, The Diff) produce items with title + URL only — `summary` is empty.
2. **Headline-only or teaser-only feeds** (FT, several wire feeds on some days) produce summaries too short to ground domain analysis.

Downstream stages (`analyze_domain`, `seams`, `cross_domain`) only see `title + summary`. Thin items become decorative — they inflate item counts without contributing substance.

## Goals

- Audit current feed quality to identify which feeds need enrichment.
- Upgrade thin RSS items by fetching article bodies and distilling them to summary-shaped content.
- Downstream stages remain unaware of enrichment — same schema, same handling code path, uniform content shape.
- Zero risk to pipeline reliability: if enrichment fails, items flow through untouched.

## Non-goals

- No paywall circumvention (bot-wall, JS-only, login-gated sites are accepted losses).
- No `robots.txt` compliance layer (these are outlets we already subscribe to via RSS; article fetch is within normal reader behavior).
- No retrieval-augmented lookups of older cached articles. The 30-day cache exists for fetch-efficiency; downstream still only sees today's items.

## Architecture

Two independent pieces of work:

1. **Audit tool** — `scripts/audit_rss_quality.py`. One-shot script, reads `output/artifacts/{date}/raw_sources.json` across a window, emits a ranked report. Used to populate `fetch_article: true` opt-ins and verify post-rollout impact. Not part of the pipeline.

2. **`enrich_articles` pipeline stage** — sits between `collect` and `compress`. Fetches, extracts, compresses article bodies for qualifying items, writes results into `item["summary"]`. Backed by a 30-day disk cache.

The audit informs configuration; the stage performs the work. They share nothing at runtime.

## `enrich_articles` stage

**Input:** `context["raw_sources"]["rss"]`
**Output:** `{"raw_sources": <mutated copy>}` with upgraded `summary` fields. Stage artifact at `output/artifacts/{date}/enrich_articles.json` with per-item status for debugging.

**Per-item decision flow:**

```
for item in rss_items:
    if feed.enrich.skip == True:            # explicit skip (even if thin)
        continue
    if feed.enrich.fetch_article == True:   # opt-in: always fetch
        enrich(item)
    elif len(item.summary) < THRESHOLD:     # thin-summary safety net
        enrich(item)
    else:
        continue                            # healthy summary, leave alone

    if fetches_this_run >= MAX_FETCHES_PER_RUN:
        log warning; break
```

**Defaults:**
- `THRESHOLD = 200` chars
- `MAX_FETCHES_PER_RUN = 40`

Both are overridable in `config.yaml` under a new `enrich_articles:` block.

**`enrich(item)`:**

1. Check disk cache at `cache/article_bodies/<sha1(url)>.json`. If hit, `status == "ok"`, and `fetched_at` within 30d → load cached `compressed_body`, skip to step 5.
2. `requests.get(url, timeout=15, headers={User-Agent: ...})`, follow redirects.
3. `trafilatura.extract(html, ...)` → raw article text. If result is `None` or shorter than `min_body_chars` (default 300) → cache as failure, return.
4. Cheap Fireworks pass (same model as `compress`, ~500 `max_tokens`) using `prompts/enrich_article_system.md` distills to 300-500 words of substance (actors, claims, numbers, mechanisms). If LLM call fails → fall back to `raw_text[:2000]`, cache with `status=llm_failed`.
5. Write cache entry with compressed body, `fetched_at`, status, raw length, and source name.
6. Assign compressed body to `item["summary"]`.

**Concurrency:** `ThreadPoolExecutor` pool of 4, matching `compress.py`. One fetch + extraction + LLM call per worker.

**Per-host rate limit:** lightweight — max 2 concurrent requests per host, 500ms min interval between same-host fetches. No token-bucket library; simple lock + last-fetched timestamp per host.

## Per-feed overrides

Each RSS feed entry in `config.yaml` gets an optional `enrich:` sub-block. All fields optional; unset fields inherit from the global block.

```yaml
- { url: "...", name: "Financial Times",
    enrich: { fetch_article: true,
              user_agent: "...",          # override default UA
              timeout_seconds: 30,        # override 15s default
              min_body_chars: 500,        # override 300 default
              skip: false } }             # force-skip (even if thin)
```

Global block:

```yaml
enrich_articles:
  enabled: true
  threshold_chars: 200
  max_fetches_per_run: 40
  cache_ttl_days: 30
  cache_failure_backoff_hours: 24
  per_host_concurrency: 2
  per_host_min_interval_ms: 500
  min_body_chars: 300
  timeout_seconds: 15
  user_agent: "MorningDigest/1.0 (morningDigest@lurkers.us)"
```

## Cache layout

`cache/article_bodies/<sha1(url)>.json`:

```json
{
  "url": "https://...",
  "fetched_at": "2026-04-19T13:22:00Z",
  "status": "ok",
  "http_status": 200,
  "raw_length": 4821,
  "compressed_body": "...",
  "source_name": "Financial Times",
  "error": ""
}
```

**Status values:** `ok`, `extraction_failed`, `http_error`, `llm_failed`, `paywall`.

**Eviction:** at stage entry, prune entries older than `cache_ttl_days`. Cheap directory scan; no background job.

**Hit policy:**
- `status == "ok"` and age within `cache_ttl_days` → cache hit, skip fetch.
- `status != "ok"` and age within `cache_failure_backoff_hours` (default 24) → cache hit, skip; do not retry.
- `status != "ok"` and older than the failure backoff → treat as miss, re-fetch.
- Corrupt JSON → treat as miss, overwrite.

**Paywall heuristic:** after extraction, if `raw_length < min_body_chars` AND the first 500 chars contain one of `"subscribe"`, `"sign in"`, `"paywall"`, `"log in to continue"` → status=`paywall` rather than `extraction_failed`. Same failure backoff either way; distinction is for audit diagnostics.

## Prompt updates

**New prompt:** `prompts/enrich_article_system.md` — distills a fetched article to 300-500 words of substance. Strips boilerplate, ads, pull quotes, related-reading blocks, author bios, CTAs. Preserves actors, claims, numbers, mechanisms. Philosophical peer of `compress_system.md` but for news articles.

**Existing prompts with a short added note:** `prompts/analyze_domain_system.md`, `prompts/seams_*.md`, `prompts/cross_domain_*.md`:

> Some item summaries include extracted article body text, not just the RSS description. Article bodies may have been captured up to 30 days ago (on the day the URL was first seen) rather than fetched fresh today; prefer analysis grounded in items from the most recent 24–48 hours but don't ignore context from older captures when it clarifies a current story.

No other prompt changes. No branching on provenance.

## Audit tool

`scripts/audit_rss_quality.py` — one-shot, stdout or `output/audits/rss_quality_{date}.md`.

**Inputs:** last N days of `output/artifacts/*/raw_sources.json` (default N=14).

**Per-feed metrics:**
- items seen across the window
- mean / median / p10 summary length (chars)
- empty-summary count and rate
- title-only rate (summary empty AND no content fallback)
- current `mode` (`rss` vs `html_index`)
- current `cap`
- whether already opted into enrichment (`enrich.fetch_article: true`)

**Output:** ranked markdown table, worst-quality first, with a `Recommend` column suggesting `fetch_article: true`, `increase cap`, `retire feed`, or `ok`.

```
| Feed | Items | Median chars | Empty % | Mode | Recommend |
|---|---|---|---|---|---|
| Brad Setser | 6 | 0 | 100% | html_index | fetch_article: true |
| Financial Times | 42 | 48 | 0% | rss | fetch_article: true |
| ... |
```

Run on demand (manual), not from the pipeline. Re-run after enrichment is live to confirm improvements.

## Error handling

The pipeline **never fails** because of enrichment. In every failure path, the item keeps its original summary and the stage continues.

| Failure | Behavior |
|---|---|
| HTTP timeout / connection error | Cache `status=http_error`, TTL 24h. Item keeps original summary. |
| HTTP 4xx / 5xx | Cache `status=http_error` with `http_status`, TTL 24h. |
| `trafilatura.extract` returns `None` or too short | Cache `status=extraction_failed` (or `paywall` if heuristic matches), TTL 24h. |
| LLM call fails / times out | Fall back to `raw_text[:2000]` written to `summary`; cache with `status=llm_failed`. Next run won't re-fetch but may retry the LLM pass on the cached raw text. |
| `MAX_FETCHES_PER_RUN` hit | Log warning with count of skipped items; pipeline continues normally. |
| Corrupt cache file | Treat as miss, overwrite. |

## Testing

All tests live under `tests/`. No live-network tests; real-world validation via the audit tool before/after rollout.

- `test_enrich_articles_cache.py` — hit/miss/expired/corrupt cache scenarios, tmp_path fixtures, no network.
- `test_enrich_articles_decision.py` — opt-in vs threshold vs skip logic, per-feed overrides, `MAX_FETCHES_PER_RUN` cap.
- `test_enrich_articles_failures.py` — mocked `requests` / `trafilatura` / `call_llm` failures; verify item flows through with original summary intact.
- `test_audit_rss_quality.py` — synthetic artifact directory, verify ranking and recommendations logic.

## Documentation updates

**`README.md`:**

1. Add `enrich_articles` bullet to the pipeline stages list under "Processes" (between `compress` and `analyze_domain`).
2. Add the `enrich_articles` node to the Pipeline Flow mermaid diagram.
3. New "Article enrichment" subsection documenting: global config block, per-feed `enrich:` override schema (with example), cache location and eviction.
4. New "Diagnostics" subsection covering: running `scripts/audit_rss_quality.py`, reading the report, and the audit → opt-in → re-audit workflow.
5. `trafilatura` noted in the dependencies/install section.

**`CLAUDE.md`:** short addition noting `output/artifacts/{date}/enrich_articles.json` as the introspection artifact for enrichment runs, and `scripts/audit_rss_quality.py` as the canonical feed-quality measurement tool.

## Pipeline manifest

Add an entry in `config.yaml` between `compress` and `analyze_domain`:

```yaml
    - name: enrich_articles
      model:
        provider: fireworks
        model: "accounts/fireworks/models/minimax-m2p7"
        max_tokens: 500
        temperature: 0.2
```

## Dependencies

Add to `requirements.txt`:

```
trafilatura>=1.8
```

## Rollout

1. Land the audit tool first; run it against existing artifacts to produce a baseline report.
2. Land the `enrich_articles` stage with no feeds opted in (`fetch_article: true` unset everywhere); threshold-based enrichment only. Observe cache growth, timing, and artifact contents over 2-3 runs.
3. Review the baseline audit, add `fetch_article: true` to the worst offenders.
4. Re-run the audit after 3-5 days. Iterate on per-feed overrides as needed.
