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

Three pieces of work:

1. **Pre-work fix in `sources/rss_feeds.py`** — a narrow body-field fallback that closes the most common cause of 0-char RSS summaries before any enrichment logic runs (see "Pre-work" below).

2. **Audit tool** — `scripts/audit_rss_quality.py`. One-shot script, reads `output/artifacts/{date}/raw_sources.json` across a window, emits a ranked report. Used to populate `fetch_article: true` opt-ins and verify post-rollout impact. Not part of the pipeline.

3. **`enrich_articles` pipeline stage** — sits between `collect` and `compress`. Fetches, extracts, compresses article bodies for qualifying items, writes results into `item["summary"]`. Backed by a 30-day disk cache.

The audit informs configuration; the stage performs the work. They share nothing at runtime.

## Pre-work: `sources/rss_feeds.py` body-field fallback

Today, `_items_from_parsed_feed` only reads `entry.get("summary", "")`. Some feeds (notably Nikkei Asia) publish their body via `<content:encoded>` instead of `<description>`, so feedparser surfaces it at `entry.content` rather than `entry.summary`. The current code returns empty.

Fix: replace the single `summary` lookup with a fallback chain:

```python
def _entry_body(entry) -> str:
    candidates = [
        entry.get("summary", ""),
        entry.get("description", ""),
    ]
    content = entry.get("content") or []
    if content:
        candidates.append(content[0].get("value", ""))
    for c in candidates:
        if c and c.strip():
            return c
    return ""
```

Pass the result through the existing `_clean_summary`. This lights up Nikkei Asia (currently 100% empty) and likely helps any other feed using the same RSS 2.0 convention. Pure fix; independent of the enrichment stage; lands first so the audit baseline reflects real empty-summary rates, not parser gaps.

## `enrich_articles` stage

**Input:** `context["raw_sources"]["rss"]`
**Output:** `{"raw_sources": <mutated copy>}` with upgraded `summary` fields. Stage artifact at `output/artifacts/{date}/enrich_articles.json` with per-item status for debugging.

**Per-item decision flow:**

Before the decision loop, dedup items by URL — the same article can legitimately appear in multiple feeds (wire stories, cross-posts). Keep the first occurrence; assign any subsequent occurrences the enriched `summary` once the first one completes, so downstream stages see consistent content for the same URL.

```
seen_urls = {}              # url -> item (first occurrence)
for item in rss_items:
    if item.url in seen_urls:
        continue            # leave duplicate; we'll backfill after enrichment
    seen_urls[item.url] = item

for item in seen_urls.values():
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

# backfill duplicates from their canonical enriched twin
for item in rss_items:
    canonical = seen_urls.get(item.url)
    if canonical and canonical is not item and canonical.summary != item.summary:
        item.summary = canonical.summary
```

**Defaults:**
- `THRESHOLD = 200` chars
- `MAX_FETCHES_PER_RUN = 40`

Both are overridable in `config.yaml` under a new `enrich_articles:` block.

**`enrich(item)`:**

1. Check disk cache at `cache/article_bodies/<sha1(url)>.json`. If hit, `status == "ok"`, and `fetched_at` within 30d → load cached `compressed_body`, skip to step 5.
2. `curl_cffi.requests.get(url, impersonate="chrome", timeout=15, cookies=cookies_jar_or_none)`, follow redirects. `curl-cffi` provides Chrome's TLS fingerprint, HTTP/2 settings, and default browser header set — defeats naive UA filters and most basic Cloudflare challenges without running a headless browser. A custom User-Agent / header override is only applied when a feed explicitly sets one (rare). If `enrich.cookies_file` is set on the feed, load it (Netscape format) and pass the jar to the request so authenticated fetches work against subscription sites.
3. `trafilatura.extract(html, ...)` → raw article text. If result is `None` or shorter than `min_body_chars` (default 300) → cache as failure, return.
4. Cheap Fireworks pass (same model as `compress`, ~500 `max_tokens`) using `prompts/enrich_article_system.md` distills to 300-500 words of substance (actors, claims, numbers, mechanisms). If LLM call fails → fall back to `raw_text[:2000]`, cache with `status=llm_failed`.
5. Write cache entry with compressed body, `fetched_at`, status, raw length, and source name.
6. Assign compressed body to `item["summary"]`.

**Concurrency:** `ThreadPoolExecutor` pool of 4, matching `compress.py`. One fetch + extraction + LLM call per worker.

**Per-host rate limit:** lightweight — max 2 concurrent requests per host, 500ms min interval between same-host fetches. No token-bucket library; simple lock + last-fetched timestamp per host.

## Per-feed overrides

Each RSS feed entry in `config.yaml` gets an optional `enrich:` sub-block. All fields optional; unset fields inherit from the global block.

```yaml
- { url: "...", name: "The Atlantic",
    enrich: { fetch_article: true,
              impersonate: "chrome",           # override browser profile (rare)
              user_agent: "...",               # override UA header (rare)
              timeout_seconds: 30,             # override 15s default
              min_body_chars: 500,             # override 300 default
              cookies_file: "secrets/atlantic.cookies.txt",  # Netscape cookies.txt
              skip: false } }                  # force-skip (even if thin)
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
  impersonate: "chrome"                   # curl-cffi browser profile
  # user_agent: unset by default; curl-cffi sends a real Chrome header set.
  # Only set this per-feed when a specific site needs a non-default UA.
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

Once enrichment artifacts exist (`enrich_articles.json`), the tool also reads those and reports, per feed:

- enrichment attempts, successes, and paywall-fail rate
- LLM-fallback rate (how often we dropped to `raw_text[:2000]`)

**Output:** ranked markdown table, worst-quality first, with a `Recommend` column suggesting `fetch_article: true`, `skip: true`, `cookies_file`, `increase cap`, `retire feed`, or `ok`. The recommendation logic distinguishes "thin summary + enrichment succeeded" (keep current config) from "thin summary + high paywall rate" (recommend `skip: true` or `cookies_file` depending on the feed).

```
| Feed | Items | Median chars | Empty % | Paywall % | Mode | Recommend |
|---|---|---|---|---|---|---|
| Brad Setser | 6 | 0 | 100% | 0% | html_index | fetch_article: true |
| Financial Times | 42 | 48 | 0% | 96% | rss | skip: true |
| The Atlantic | 54 | 90 | 0% | 12% | rss | ok (cookies working) |
| ... |
```

Run on demand (manual), not from the pipeline. Re-run after enrichment is live to confirm improvements.

**Empty-input behavior:** if no artifact directories are found (fresh clone, first-time setup), the tool prints a short "no artifacts found at output/artifacts/" notice and exits 0 — never crashes. Same treatment if artifacts exist but contain no RSS items.

## Error handling

The pipeline **never fails** because of enrichment. In every failure path, the item keeps its original summary and the stage continues.

| Failure | Behavior |
|---|---|
| HTTP timeout / connection error | Cache `status=http_error`, backoff `cache_failure_backoff_hours`. Item keeps original summary. |
| HTTP 4xx / 5xx | Cache `status=http_error` with `http_status`, same backoff. |
| `trafilatura.extract` returns `None` or too short | Cache `status=extraction_failed` (or `paywall` if heuristic matches), same backoff. |
| LLM call fails / times out | Fall back to `raw_text[:2000]` written to `summary`; cache with `status=llm_failed`. Next run won't re-fetch but may retry the LLM pass on the cached raw text. |
| `MAX_FETCHES_PER_RUN` hit | Log warning with count of skipped items; pipeline continues normally. |
| Corrupt cache file | Treat as miss, overwrite. |

## Testing

All tests live under `tests/`. No live-network tests; real-world validation via the audit tool before/after rollout.

- `test_enrich_articles_cache.py` — hit/miss/expired/corrupt cache scenarios, tmp_path fixtures, no network.
- `test_enrich_articles_decision.py` — opt-in vs threshold vs skip logic, per-feed overrides, `MAX_FETCHES_PER_RUN` cap.
- `test_enrich_articles_failures.py` — mocked `curl_cffi.requests` / `trafilatura` / `call_llm` failures; verify item flows through with original summary intact.
- `test_audit_rss_quality.py` — synthetic artifact directory, verify ranking and recommendations logic.

## Documentation updates

**`README.md`:**

1. Add `enrich_articles` bullet to the pipeline stages list under "Processes" (between `compress` and `analyze_domain`).
2. Add the `enrich_articles` node to the Pipeline Flow mermaid diagram.
3. New "Article enrichment" subsection documenting: global config block, per-feed `enrich:` override schema (with example), cache location and eviction.
4. New "Authenticated fetches" subsection explaining the `cookies_file` pattern: how to export cookies.txt from a browser, where to put it (`secrets/` outside git), how to mount it in Docker, when to refresh.
5. New "Diagnostics" subsection covering: running `scripts/audit_rss_quality.py`, reading the report, and the audit → opt-in → re-audit workflow.
6. `trafilatura` and `curl-cffi` noted in the dependencies/install section.

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
curl-cffi>=0.7
```

`curl-cffi` ships its own bundled `libcurl-impersonate` binaries for Linux x86_64 and arm64 via wheels; no extra system packages required inside the Docker image.

## Known constraints per feed

Baseline measurement from `output/artifacts/2026-04-19/raw_sources.json` (109 items, 31 sources) drives these recommendations. They're starting config; the audit tool can refine over time.

**Hard paywalls — set `enrich.skip: true`:**

Fetching will hit a paywall preview and waste the per-run budget. Current thin-but-nonzero RSS summaries are better than a failed fetch.

- Financial Times
- The Economist (Finance & Economics)
- Nikkei Asia *(re-evaluate after the pre-work fix; may no longer be empty)*
- Nature
- Science Magazine

**Authenticated paywall — use `enrich.cookies_file`:**

- **The Atlantic** — user holds a subscription. Export a Netscape `cookies.txt` from a logged-in browser (e.g. the "Get cookies.txt LOCALLY" extension) into `cookies/atlantic.cookies.txt` at the project root. Set `fetch_article: true` and `cookies_file:` on the feed. Cookies expire periodically; re-export when `enrich_articles.json` starts showing `paywall` status for Atlantic URLs.

**Substack cluster — no special config, but expect heavy enrichment volume:**

Several Substacks publish very short teasers (China Talk ~36 chars, Slow Boring ~27, Cosmopolitan Globalist ~60, Daniel Drezner ~66, Adam Tooze ~72, Defense Tech and Acquisition ~59). These will all trigger threshold-based enrichment. Substack articles are almost always open, so fetches should succeed. Budget-wise this alone consumes ~8-10 of the 40 per-run fetch slots — expected and acceptable.

**html_index scrapers — already handled, but prioritized targets:**

Brad Setser, China Global South Project — 100% empty summaries by design. Set `fetch_article: true` at rollout.

**Cookie file handling:** `cookies_file` paths must resolve to files outside the git repo. Reuse the existing file-mount pattern (same as `config.yaml`): create a `cookies/` directory at the project root, add it to `.gitignore` and `.dockerignore`, and mount it read-only in `docker-compose.yml`:

```yaml
volumes:
  - ./config.yaml:/app/config.yaml:ro
  - ./cookies:/app/cookies:ro    # new
  - ./output:/app/output
  - ./tests:/app/tests:ro
```

API-key-style secrets stay in `.env`; cookie *files* get the same treatment as `config.yaml`. No new secrets-handling concept.

## Pre-implementation sanity checks

Four assumptions in this spec haven't been verified. Do these first; they're cheap and any failure changes the design.

1. **curl-cffi installs in the existing Docker image.** The base image is `python:3.12-slim` (confirmed), so manylinux wheels apply. Sanity-check: `docker compose run --rm morning-digest python -c "from curl_cffi import requests; print(requests.get('https://example.com', impersonate='chrome').status_code)"`.

2. **trafilatura extraction quality on Substack DOM.** Run `trafilatura` against 3-4 Substack article URLs (open posts, e.g. recent Slow Boring, Adam Tooze, Simon Willison). Confirm the extracted text is clean article prose, not navigation/subscribe-CTA noise. If quality is poor, add a Substack-specific config (or a fallback readability pass) to the plan.

3. **Browser-exported `cookies.txt` is readable by curl-cffi.** Export a test cookies file from a logged-in Atlantic session, load it in a curl-cffi session, verify the jar has the expected session cookies and that a GET to a paywalled article returns full HTML (not a login wall). If parsing fails, add an adapter step that normalizes to curl-cffi's expected format.

4. **Fireworks quota headroom.** Check current monthly usage dashboard; up to 40 extra `minimax-m2p7` calls per run at ~500 tokens output is ~20k tokens/day additional. Confirm this is comfortably within your plan.

Deliver these as a short "pre-flight" PR or verification log before the stage implementation starts.

## Implementation leverage — subagents

The three pieces of work are largely independent and well-suited to parallel subagent execution:

- **Subagent A** — Pre-work fix in `sources/rss_feeds.py` (body-field fallback) + tests.
- **Subagent B** — `scripts/audit_rss_quality.py` audit tool + tests. Depends on nothing else; can start immediately.
- **Subagent C** — `enrich_articles` stage (decision logic, cache layer, curl-cffi client, LLM distillation, artifact emission) + tests. Depends on the pre-work fix landing first so its tests use a consistent baseline.

The prompt update (adding the short note to `analyze_domain_system.md`, `seams_*.md`, `cross_domain_*.md`) is a small focused task — assign to a single subagent to keep phrasing consistent.

Parallelizable test-writing within each subagent: each test file (`test_enrich_articles_cache.py`, `test_enrich_articles_decision.py`, `test_enrich_articles_failures.py`, `test_audit_rss_quality.py`) is independent and can be split across subagents if the main agent is pacing the work.

Coordinate at integration points: pipeline manifest entry in `config.yaml` (single line), `requirements.txt` updates, and `README.md` / `CLAUDE.md` documentation. These land in a single final commit.

## Rollout

1. Complete the pre-implementation sanity checks above.
2. Land the `rss_feeds.py` body-field fallback fix. Re-run pipeline once to confirm Nikkei summaries go from 0 → non-empty.
3. Land the audit tool; run it against existing artifacts (including the fresh post-fix run) to produce a baseline report.
4. Land the `enrich_articles` stage with the pre-seeded per-feed config above (`skip: true` on hard paywalls, `cookies_file` on The Atlantic, `fetch_article: true` on html_index sources). Observe cache growth, timing, and artifact contents over 2-3 runs.
5. Review the baseline audit vs. post-rollout audit. Adjust per-feed overrides for outliers.
6. Re-run the audit after 3-5 days. Iterate on per-feed overrides as needed.
