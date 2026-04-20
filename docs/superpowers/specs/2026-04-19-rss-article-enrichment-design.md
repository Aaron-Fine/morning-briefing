# RSS Article Enrichment — Design

**Date:** 2026-04-19
**Status:** Design approved, implementation pending

## Problem

RSS feeds expose article content inconsistently. Some provide full article bodies in `content:encoded`, some provide usable summaries, some provide teaser-only blurbs, and some provide title + URL only. Downstream analysis should not have to care which acquisition path succeeded.

Some feeds arrive too thin for downstream analysis:

1. **`html_index`-scraped sources** (Brad Setser, Reuters Markets, China Global South, The Diff) produce items with title + URL only — `summary` is empty.
2. **Headline-only or teaser-only feeds** (FT, several wire feeds on some days) produce summaries too short to ground domain analysis.

Downstream stages (`analyze_domain`, `seams`, `cross_domain`) only see `title + summary`. Thin items become decorative — they inflate item counts without contributing substance.

## Goals

- Audit current feed quality to identify which feeds need normalization, fetching, or explicit skipping.
- Normalize RSS items to one canonical downstream summary, using the best available source text from RSS fields or fetched article bodies.
- Downstream stages remain unaware of enrichment — same schema, same handling code path, uniform content shape.
- Zero risk to pipeline reliability: if enrichment fails, items flow through untouched.

## Non-goals

- No paywall circumvention (bot-wall, JS-only, login-gated sites are accepted losses).
- No `robots.txt` compliance layer (these are outlets we already subscribe to via RSS; article fetch is within normal reader behavior).
- No retrieval-augmented lookups of older cached articles. The 30-day cache exists for fetch-efficiency; downstream still only sees today's items.

## Architecture

Four pieces of work:

1. **Pre-work fix in `sources/rss_feeds.py`** — a narrow body-field fallback that closes the most common cause of 0-char RSS summaries before any enrichment logic runs (see "Pre-work" below).

2. **Content selection helper** — `sources/article_content.py`. Chooses the best native RSS source text and decides whether feed policy requires an article fetch before normalization.

3. **Audit tool** — `scripts/audit_rss_quality.py`. One-shot script, reads `output/artifacts/{date}/raw_sources.json` plus enrichment artifacts across a window, emits a ranked report. Used to tune feed strategies and verify post-rollout impact. Not part of the pipeline.

4. **`enrich_articles` pipeline stage** — sits between `collect` and `compress`. Selects the best available native RSS text, fetches/extracts article bodies only when policy or thin native text requires it, distills long source text to a canonical summary, sanitizes the final summary, and writes it into `item["summary"]`. Backed by a 30-day disk cache.

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
**Output:** `{"raw_sources": <mutated copy>, "enrich_articles": {"records": [...]}}` with upgraded `summary` fields. Stage artifact at `output/artifacts/{date}/enrich_articles.json` with per-item status, provenance, and before/after lengths for debugging.

The stage contract is:

```
raw feed item -> best available source text -> canonical sanitized summary
```

The final `item["summary"]` must be comparable across acquisition paths. Do not preserve raw/full article text in prompt-visible fields. Store provenance in the enrichment artifact instead.

Because this stage runs after `collect` source sanitization, it must sanitize every final summary before assignment. Downstream prompt builders should still sanitize defensively at their own prompt boundary; `stages/seams.py` currently needs this update because it formats raw source snippets directly.

**Per-item decision flow:**

Before the decision loop, dedup items by URL — the same article can legitimately appear in multiple feeds (wire stories, cross-posts). Keep the first occurrence; assign any subsequent occurrences the enriched `summary` once the first one completes, so downstream stages see consistent content for the same URL.

```
seen_urls = {}              # url -> item (first occurrence)
for item in rss_items:
    if item.url in seen_urls:
        continue            # leave duplicate; we'll backfill after enrichment
    seen_urls[item.url] = item

for item in seen_urls.values():
    if feed.enrich.strategy == "skip" or feed.enrich.skip == True:
        continue

    source_text = best_native_rss_text(item)        # content -> summary -> description

    if feed.enrich.strategy in {"fetch", "fetch_with_cookies"}:
        source_text = fetched_article_text_or(source_text)
    elif len(source_text) < min_usable_chars:
        source_text = fetched_article_text_or(source_text)

    if len(source_text) >= summarize_above_chars:
        item.summary = canonical_distillation(source_text)
    elif source_text:
        item.summary = canonical_cleanup(source_text)
    else:
        continue

    item.summary = sanitize_source_content(item.summary, max_chars=canonical_summary_max_chars)

    if fetches_this_run >= MAX_FETCHES_PER_RUN:
        log warning; break

# backfill duplicates from their canonical enriched twin
for item in rss_items:
    canonical = seen_urls.get(item.url)
    if canonical and canonical is not item and canonical.summary != item.summary:
        item.summary = canonical.summary
```

**Defaults:**
- `min_usable_chars = 200`
- `summarize_above_chars = 800`
- `canonical_summary_max_chars = 700`
- `MAX_FETCHES_PER_RUN = 40`

All are overridable in `config.yaml` under a new `enrich_articles:` block.

**`enrich(item)`:**

1. Choose native source text from RSS fields, preferring full body-like fields (`content:encoded` / `entry.content`) over shorter summaries when available.
2. If the native source text is long enough and `strategy: fetch` / `strategy: fetch_with_cookies` is not set, skip network fetch and normalize the native text.
3. Check disk cache at `cache/article_bodies/<sha1(url)>.json` before fetching. If hit, `status == "ok"`, and `fetched_at` within 30d → load cached extracted source text or canonical summary as applicable.
4. `curl_cffi.requests.get(url, impersonate="chrome", timeout=15, cookies=cookies_jar_or_none)`, follow redirects. `curl-cffi` provides Chrome's TLS fingerprint, HTTP/2 settings, and default browser header set — defeats naive UA filters and most basic Cloudflare challenges without running a headless browser. A custom User-Agent / header override is only applied when a feed explicitly sets one (rare). If `enrich.cookies_file` is set on the feed, load it (Netscape format) and pass the jar to the request so authenticated fetches work against subscription sites.
5. `trafilatura.extract(html, ...)` → raw article text. If result is `None` or shorter than `min_body_chars` (default 300) → cache as failure, return.
6. Cheap Fireworks pass (same model as `compress`, ~500 `max_tokens`) using `prompts/enrich_article_system.md` distills any long native or fetched source text to 500-700 characters / about 80-120 words of substance (actors, claims, numbers, mechanisms). If LLM call fails → fall back to a sanitized source-text excerpt within the canonical limit, cache with `status=llm_failed`.
7. Sanitize the final summary before assigning it to `item["summary"]`; enrichment runs after `collect`, so it cannot rely on collect-time sanitization.
8. Write cache entry and artifact record with final summary, source-text origin, `fetched_at`, status, raw length, summary length, source name, and error.
9. Assign the sanitized canonical summary to `item["summary"]`.

**Concurrency:** `ThreadPoolExecutor` pool of 4, matching `compress.py`. One fetch + extraction + LLM call per worker.

**Per-host rate limit:** lightweight — max 2 concurrent requests per host, 500ms min interval between same-host fetches. No token-bucket library; simple lock + last-fetched timestamp per host.

## Per-feed overrides

Each RSS feed entry in `config.yaml` gets an optional `enrich:` sub-block. All fields optional; unset fields inherit from the global block.

```yaml
- { url: "...", name: "The Atlantic",
    enrich: { impersonate: "chrome",           # override browser profile (rare)
              user_agent: "...",               # override UA header (rare)
              strategy: "fetch_with_cookies",  # auto | rss_only | fetch | fetch_with_cookies | skip
              timeout_seconds: 30,             # override 15s default
              min_body_chars: 500,             # override 300 default
              cookies_file: "secrets/atlantic.cookies.txt",  # Netscape cookies.txt
              skip: false } }                  # force-skip (even if thin)
```

Global block:

```yaml
enrich_articles:
  enabled: true
  min_usable_chars: 200
  summarize_above_chars: 800
  canonical_summary_max_chars: 700
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
  "source_text_origin": "fetched_html",
  "raw_length": 4821,
  "summary_length": 642,
  "canonical_summary": "...",
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

**New prompt:** `prompts/enrich_article_system.md` — distills long native RSS bodies or fetched article text to 500-700 characters / about 80-120 words of substance. Strips boilerplate, ads, pull quotes, related-reading blocks, author bios, CTAs. Preserves actors, claims, numbers, mechanisms. Philosophical peer of `compress_system.md` but for per-item news summaries.

**Existing prompts with a short added note:** `prompts/analyze_domain_system.md`, `prompts/seams_*.md`, `prompts/cross_domain_*.md`:

> Item summaries are canonicalized from the best available source text: RSS body fields when available, otherwise fetched article text where feed policy allows. Treat each summary as the digest's normalized view of the source item; article text may have been captured up to 30 days ago (on the day the URL was first seen) rather than fetched fresh today.

No other prompt changes. No branching on provenance.

## Audit tool

`scripts/audit_rss_quality.py` — one-shot, stdout or `output/audits/rss_quality_{date}.md`.

**Inputs:** last N days of `output/artifacts/*/raw_sources.json` (default N=14).

**Per-feed metrics:**
- items seen across the window
- mean / median / p10 final summary length (chars)
- mean / median native source-text length before enrichment
- empty-summary count and rate
- title-only rate (no native RSS text and no successful fetch)
- current `mode` (`rss` vs `html_index`)
- current `cap`
- current enrichment strategy (`auto`, `rss_only`, `fetch`, `fetch_with_cookies`, `skip`)

Once enrichment artifacts exist (`enrich_articles.json`), the tool also reads those and reports, per feed:

- enrichment attempts, successes, HTTP-fail rate, extraction-fail rate, and paywall-fail rate
- LLM-fallback rate (how often we used a sanitized source-text excerpt instead of model output)

**Output:** ranked markdown table, worst-quality first, with a `Recommend` column suggesting `strategy: fetch`, `strategy: rss_only`, `strategy: skip`, `cookies_file`, `increase cap`, `retire feed`, or `ok`. The recommendation logic distinguishes "thin summary + enrichment succeeded" (keep current config) from "thin summary + high paywall rate" (recommend `strategy: skip` or `cookies_file` depending on the feed).

```
| Feed | Items | Median chars | Empty % | Paywall % | Mode | Recommend |
|---|---|---|---|---|---|---|
| Brad Setser | 6 | 0 | 100% | 0% | html_index | strategy: fetch |
| Financial Times | 42 | 48 | 0% | 96% | rss | strategy: skip |
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
| LLM call fails / times out | Fall back to a sanitized excerpt only if the source text is usable; cap it at `canonical_summary_max_chars`, cache with `status=llm_failed`, and keep artifact provenance. |
| `MAX_FETCHES_PER_RUN` hit | Log warning with count of skipped items; pipeline continues normally. |
| Corrupt cache file | Treat as miss, overwrite. |

## Testing

All tests live under `tests/`. No live-network tests; real-world validation via the audit tool before/after rollout.

- `test_article_content.py` — native RSS source-text selection, strategy resolution, fetch/distillation decisions.
- `test_article_cache.py` — hit/miss/expired/corrupt cache scenarios, tmp_path fixtures, no network.
- `test_enrich_articles.py` — canonical summary normalization, strategy behavior, dedup, sanitization, per-host throttling, `MAX_FETCHES_PER_RUN`, and failure paths.
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

**Hard paywalls — set `enrich.strategy: "skip"`:**

Fetching will hit a paywall preview and waste the per-run budget. Current thin-but-nonzero RSS summaries are better than a failed fetch.

- Financial Times
- The Economist (Finance & Economics)
- Nikkei Asia *(re-evaluate after the pre-work fix; may no longer be empty)*
- Nature
- Science Magazine

**Authenticated paywall — use `enrich.cookies_file`:**

- **The Atlantic** — user holds a subscription. Export a Netscape `cookies.txt` from a logged-in browser (e.g. the "Get cookies.txt LOCALLY" extension) into `cookies/atlantic.cookies.txt` at the project root. Set `strategy: "fetch_with_cookies"` and `cookies_file:` on the feed. Cookies expire periodically; re-export when `enrich_articles.json` starts showing `paywall` status for Atlantic URLs.

**Substack cluster — no special config, but expect heavy enrichment volume:**

Several Substacks publish very short teasers (China Talk ~36 chars, Slow Boring ~27, Cosmopolitan Globalist ~60, Daniel Drezner ~66, Adam Tooze ~72, Defense Tech and Acquisition ~59). These will all trigger threshold-based enrichment. Substack articles are almost always open, so fetches should succeed. Budget-wise this alone consumes ~8-10 of the 40 per-run fetch slots — expected and acceptable.

**html_index scrapers — already handled, but prioritized targets:**

Brad Setser, China Global South Project — 100% empty summaries by design. Set `strategy: "fetch"` at rollout.

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

The implementation pieces are partly independent and well-suited to parallel subagent execution:

- **Subagent A** — Pre-work fix in `sources/rss_feeds.py` (body-field fallback) + tests.
- **Subagent B** — `sources/article_content.py` content-selection helper + tests. Depends on nothing else; can start immediately.
- **Subagent C** — `scripts/audit_rss_quality.py` audit tool + tests. Depends on nothing else; can start immediately.
- **Subagent D** — `enrich_articles` stage (decision logic, cache layer, curl-cffi client, LLM normalization, per-host throttling, sanitization, artifact emission) + tests. Depends on the pre-work fix and content-selection helper landing first so its tests use a consistent baseline.

The prompt update (adding the short note to `analyze_domain_system.md`, `seams_*.md`, `cross_domain_*.md`) is a small focused task — assign to a single subagent to keep phrasing consistent.

Parallelizable test-writing within each subagent: each test file (`test_enrich_articles_cache.py`, `test_enrich_articles_decision.py`, `test_enrich_articles_failures.py`, `test_audit_rss_quality.py`) is independent and can be split across subagents if the main agent is pacing the work.

Coordinate at integration points: pipeline manifest entry in `config.yaml` (single line), `requirements.txt` updates, and `README.md` / `CLAUDE.md` documentation. These land in a single final commit.

**Commit and push discipline (applies to every subagent and to the main agent):**

- **One feature per commit.** Pre-work fix, audit tool, enrich-articles stage, prompt updates, docs — each is its own commit. Do not accumulate unrelated changes in a single commit.
- **Stage files explicitly** (`git add <file>`); never `git add -A` or `git add .`.
- **Commit at the end of each turn** if tracked files are modified.
- **Push at least once per batch of work** (e.g. after the pre-work fix lands, after the audit tool lands, after the enrich stage lands), and at the end of a work session. Do not push mid-feature when code is broken or partial.

These rules match the project's `CLAUDE.md` policy and must be passed through to any subagent the main agent dispatches.

## Rollout

1. Complete the pre-implementation sanity checks above.
2. Land the `rss_feeds.py` body-field fallback fix. Re-run pipeline once to confirm Nikkei summaries go from 0 → non-empty.
3. Land the audit tool; run it against existing artifacts (including the fresh post-fix run) to produce a baseline report.
4. Land the `enrich_articles` stage with the pre-seeded per-feed config above (`strategy: "skip"` on hard paywalls, `strategy: "fetch_with_cookies"` on The Atlantic, `strategy: "fetch"` on html_index sources). Observe cache growth, timing, and artifact contents over 2-3 runs.
5. Review the baseline audit vs. post-rollout audit. Adjust per-feed overrides for outliers.
6. Re-run the audit after 3-5 days. Iterate on per-feed overrides as needed.
