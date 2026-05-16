# LemonGraph / LemonGrenade vs. Morning-Digest seams — assessment

Status: exploration / opinionated. Cites both codebases by file:line. No code
changes proposed beyond the prototype sketch in §5.

## 1. TL;DR

The hypothesis is **partially right, mostly for the wrong reason**. The
pattern that matters in LemonGrenade is *not* "graph storage replaces JSON
artifacts" — it's **"adapters declare a query pattern over a shared
intermediate state, and a scheduler triggers them when the pattern matches."**
That's a real architectural improvement over what `cross_domain` and `seams`
do today, which is "stuff every artifact into a giant prompt and ask the LLM
to think about it."

- **Biggest win available:** make `connection_hooks` (which already exist as
  per-item `{entity, region, theme, policy}` tuples in `analyze_domain.py:406`)
  into first-class graph edges, and run cross-domain detection as an
  *index lookup over shared hooks* instead of "give the LLM all seven desk
  outputs and pray." This kills the "loses category coverage when prompt is
  full" failure mode without changing the LLM stack.
- **Biggest trap:** thinking you need LemonGraph (LMDB-backed C library) or
  LemonGrenade (Storm/Mesos/Akka/RabbitMQ/MongoDB) to do this. You don't.
  Both of those projects are 2017-era NSA infrastructure. The *idea* is
  good; the *implementation* is wildly out of scale for a single-user
  daily-digest pipeline. If you adopt either as a dependency you will spend
  more time fighting JVM/RabbitMQ/storm-supervisor than improving digests.
- **Net recommendation:** steal the pattern (graph-shaped intermediate state +
  query-driven adapters), implement it in ~200 lines of Python over SQLite
  or a plain dict-of-dicts, and don't touch the NSA repos. See §5 and §7.

## 2. What LemonGraph and LemonGrenade actually are

Both repos are NSA tech-preview releases (see
`/tmp/claude-1000/lemon/lemongrenade/README.md:1` and
`/tmp/claude-1000/lemon/lemongraph/README.md:1`); the Java side hasn't seen
substantive work since ~2018, the Python side ~2019. Read this
section assuming "abandoned-but-documented research code," not "live
infrastructure."

### LemonGraph (the storage layer)

A log-structured graph DB built on **Symas LMDB** (the same B-tree key/value
store OpenLDAP uses). C core (`/tmp/claude-1000/lemon/lemongraph/lib/lemongraph.c`)
plus Python bindings (`/tmp/claude-1000/lemon/lemongraph/LemonGraph/__init__.py`).
What it actually offers:

- **Nodes** — uniqued by `(type, value)` tuple within a graph.
- **Edges** — directed, uniqued by `(src, tgt, type, value)`.
- **Properties** — k/v on graph, nodes, edges, *and other properties*
  (recursive). Custom serializers per key (json/msgpack).
- **Log-structured history** — every mutation increments a graph-wide ID
  (`txn.lastID`, `txn.nextID`). Queries can be evaluated *as of* a log
  position, and **streaming queries** return new matches added since a
  bookmark. This is the load-bearing feature for the workflow pattern.
- **Query language** (`MatchLGQL.py:1-80`) — node/edge chain patterns:
  `n(type~/foo/i,prop="bar")-e()->n(prop2!=null)`. Regex match on properties,
  inferred-vs-captured components, ad-hoc and streaming evaluation modes.
- LMDB inheritances: single-writer multi-reader MVCC, snapshots, manual
  mapsize management, "don't open the db twice in one process."

What it is *not*: a triple store, a property graph with a real query
optimizer, anything you'd compare to Neo4j/DuckDB. It's optimized for one
workload — incremental seed-set expansion — and admits as much in its README
("primary use case is to support streaming seed set expansion").

### LemonGrenade (the orchestrator)

A workflow engine where **adapters are query-driven**. Reading the example
adapters
(`/tmp/claude-1000/lemon/lemongrenade/examples/src/main/java/lemongrenade/examples/adapters/HelloWorldAdapter.java:13-64`,
`PlusBangAdapter.java:13-75`) is the fastest way to grasp the contract:

```java
@Override public String getAdapterQuery() { return "n(hello~/.*/i)"; }
@Override public void process(LGPayload input, LGCallback callback) { ... }
```

Each adapter declares:
1. A **query pattern** over the job's graph
   (`getAdapterQuery()` and `getRequiredAttributes()`).
2. A **`process(payload, callback)`** function that consumes matching nodes
   (`payload.getRequestNodes()`) and emits new nodes/edges
   (`payload.addResponseNode()`, `addResponseEdge()`).

The coordinator
(`/tmp/claude-1000/lemon/lemongrenade/core/src/main/java/lemongrenade/core/coordinator/CoordinatorBolt.java:25-100`)
holds the job graph, watches for new graph state, finds adapters whose
patterns now match, and dispatches tasks. New nodes from adapter responses
are merged back; the cycle repeats until no adapter pattern matches new
state, or `depth` is exhausted, or `ttl` elapses
(`docs/coordinator-api.txt:lines on /api/job POST`).

Heavy machinery layered on this idea:
- **Storm** topology for parallel adapter dispatch (`CoordinatorTopology.java`)
- **RabbitMQ** as the work queue (`SubmitToRabbitMQ.java`,
  `RabbitMQSpout.java`)
- **MongoDB** for job state, adapter registry, and history
  (`coordinator/JobManager.java:17-55`,
  `coordinator/AdapterManager.java:35-95`)
- **Zookeeper** + **supervisord** wiring per the README install steps
- A REST API + webapp + the LemonGraph HTTP server passthrough

The actual conceptual surface — adapter = `(query pattern, process fn)`,
coordinator = "loop until no new matches" — is maybe 300 lines of logic
buried in 40+ Java files. The Java/Storm/Mongo stack is operational
weight, not the idea.

## 3. What the current seams / cross-domain stages do

Pipeline order
(`/home/aaron/Morning-Digest/config/pipeline.yaml:16-110`): collect →
enrich_articles → compress → analyze_domain → calendar/weather/spiritual →
**seams** → **cross_domain** → coverage_gaps → assemble.

### `analyze_domain` — `/home/aaron/Morning-Digest/stages/analyze_domain.py` (1231 lines)

- Defines seven "desk" configs in `_DOMAIN_CONFIGS`
  (`analyze_domain.py:63-388`): geopolitics_events, defense_space, ai_tech,
  energy_materials, culture_structural, science_biotech, econ, plus an
  eighth `perspective` desk (`:106-135`).
- Each desk takes a category-filtered slice of `raw_sources["rss"]` and
  channel-filtered transcripts, runs **one LLM call per desk in parallel**
  (`_run_all_domains`, `:938-991`, `ThreadPoolExecutor(max_workers=4)`).
- Output schema per item (`:394-412`) — and this is the load-bearing point
  for the rest of this doc — already includes a structured `connection_hooks`
  array of `{entity, region, theme, policy}` tuples.
- Post-processing: `_rebalance_categories` (around `:790-853`) ensures
  intra-desk category coverage by synthesizing a fallback item if a
  desk's prompt produced nothing for one of its routed categories.

### `cross_domain` — `/home/aaron/Morning-Digest/cross_domain/stage.py` (215 lines, plus `parse.py`/`prompt.py`)

Two-turn LLM pass:
- **Plan turn** (`stage.py:101-131`): prompt = "here's all seven desk
  outputs, here's `seam_data`, here's recent raw sources, pick deep dives
  / worth-reading / cross-domain connections." Returns `cross_domain_plan`.
- **Execute turn** (`stage.py:133-145`): same prompt minus planning,
  produces final `cross_domain_output`.
- Then deterministic post-processing in `parse.py`:
  `_recompute_source_depth` (`:452-465`) recounts distinct registered
  domains from links and **overrides** the LLM's claimed source_depth.
  `_cap_at_a_glance_items` (`:225-289`) enforces topic + outlet diversity
  with a deterministic priority loop. `_ensure_primary_glance_coverage`
  (`:318-352`) re-injects a primary-tag item if the LLM dropped war/ai/
  defense.

The pattern is unmistakable: **the LLM is asked to do graph reasoning over
desk items, then we patch up the parts where the LLM consistently fails
(source-depth honesty, category diversity, outlet caps) with deterministic
Python.** Each patch is real evidence of friction.

### `seams` — `/home/aaron/Morning-Digest/stages/seams.py` (772 lines)

Same shape. One LLM call (`run`, `:695-771`) takes domain_analysis +
raw_sources + transcripts + perspective framing, asks for per-item
"framing/selection/causal/magnitude divergence" annotations
(`_VALID_SEAM_TYPES` `:37-43`), then `_validate_seam_annotations`
(`:390-481`) hard-drops any annotation that doesn't satisfy the evidence
gate (`_evidence_passes_gate`, `:373-387`: ≥2 distinct sources, ≥2 useful
excerpts).

The evidence gate is exactly the kind of structural check you'd express as a
graph query: *"for each candidate seam node, count the distinct
`source` properties on attached `evidence` edges; require ≥2."*

### `coverage_gaps` — `/home/aaron/Morning-Digest/stages/coverage_gaps.py` (229 lines)

Reads `domain_analysis` + `cross_domain_plan`, builds a flat text summary
(`_build_domain_summary`, `:32-47`), prompts the LLM for "what important
things are missing." Maintains an append-only history file at
`output/coverage_gaps_history.jsonl` for recurrence detection
(`_load_recent_history`, `:62-76`).

### `assemble` — `/home/aaron/Morning-Digest/stages/assemble.py` (454 lines)

Merges `cross_domain_output` (Phase 3 path) or `domain_analysis`
(Phase 1 fallback) plus all peripheral data, enforces per-outlet caps
again (`_enforce_source_caps`, `:110-146`), attaches at most one seam
annotation to each at-a-glance item (`_select_inline_seam_annotations`,
`:149-184`).

### Data flow

Stages are pure functions `(context, config, model_config) -> dict`; the
runner merges returned dicts into `context`. Every artifact is also
written to `output/artifacts/YYYY-MM-DD/*.json` (32 JSON files for the
2026-04-28 run, see directory listing). Inter-stage transport is in-memory
via the context dict; on-disk artifacts are for inspection and replay,
not for the pipeline itself.

### Where the architecture struggles (symptoms, not opinions)

1. **Pairwise / N-way reasoning is being shoved through a single LLM
   prompt.** `cross_domain.stage.run` literally formats all seven desk
   outputs into one user message
   (`cross_domain/prompt.py` via `_plan_user_content`,
   `cross_domain/stage.py:108-114`). When it drops a connection or omits a
   primary tag, we patch in Python (`_ensure_primary_glance_coverage`,
   `parse.py:318-352`).
2. **Source-depth honesty is computed twice** — once by the LLM, once by
   `_recompute_source_depth` (`parse.py:452-465`) which deterministically
   overrides. The LLM-emitted value is essentially noise.
3. **Per-outlet caps appear in three places**: `cross_domain.parse._cap_at_a_glance_items`,
   `assemble._enforce_source_caps`, and `analyze_domain._rebalance_categories`'s
   `max_category_share` (`:827-849`). Three layers of dedup.
4. **`connection_hooks` are produced but barely consumed.** Search for
   `connection_hooks` outside `analyze_domain.py` and `assemble.py`: they're
   passed through to display, not used as a routing signal. The most
   structural piece of cross-domain metadata is essentially decorative.
5. **Seam evidence gate** (`seams.py:373-387`) is a graph constraint
   ("≥2 distinct source nodes attached to this seam") expressed as a
   hand-rolled list traversal.
6. **Category-rebalance synthesizes fake items** (`analyze_domain.py:790-853`)
   to compensate when the LLM forgets a routed category. This is a
   coverage query expressed as imperative patching.

Every one of those symptoms is an instance of "we have graph-shaped
relationships, but no graph machinery, so the LLM does the joining and we
clean up after."

## 4. The mapping

| LemonGraph/LemonGrenade idea | Verdict | Where it applies in Morning-Digest |
|---|---|---|
| **Nodes/edges/properties as the canonical state** | **enhance** | `connection_hooks` (`analyze_domain.py:406`) are already edge candidates: each hook becomes an edge from a desk-item node to an entity/theme/policy node. Currently they're nested dicts in JSON. |
| **Log-structured incremental queries** (streaming, `start=pos`) | **does not fit** | Morning-Digest is a daily batch. Within one run, log positions don't help; across runs, we want fresh state. The streaming feature is the whole point of LemonGraph and most of it is wasted here. |
| **Graph query language** (`n(prop~/.../)-e()->n()`) | **enhance, simplified** | "Items sharing ≥1 entity hook" or "items in domain A whose theme also appears in domain B" is a real query. But you don't need LMDB+CFFI for this — it's two nested dict iterations. |
| **Adapter contract: `(query, process)`** | **replace** | The seams + cross_domain LLM prompts are doing what should be N independent adapter calls: "evidence-gate adapter," "connection-finder adapter," "source-cap adapter," "category-rebalance adapter." Each currently exists as imperative Python *or* is buried in a giant prompt. |
| **Trigger model: adapter fires when its query matches new state** | **enhance** | Today the pipeline is a static DAG. A trigger model lets `cross_domain` re-run *only* if a desk produced new items with hooks unseen by the previous run. Useful for incremental re-runs (e.g., late-arriving feeds). |
| **`postaction` API: re-run a specific adapter on a node subset** | **enhance** | Useful for "research_request" loop — `analyze_domain` already does a second pass with fetched articles (`_run_domain_research`, `:1040+`). That's a postaction in disguise. |
| **Mesos/Storm/Akka/RabbitMQ/MongoDB/Zookeeper** | **do not import** | Operational complexity for a daily single-user pipeline. ThreadPoolExecutor (already in `analyze_domain.py:38, 975`) is the right scale. |
| **LMDB-backed graph file** | **do not import** | LMDB is excellent but the workload here (~hundreds of nodes, ~thousands of edges per run, written once and read for ~5 minutes) does not warrant a C dependency. SQLite or even a Python dict is correct. |
| **MongoDB job state** | **do not import** | Already covered by `output/artifacts/YYYY-MM-DD/`. JSON-on-disk is fine. |
| **Job-scoped graphs (one graph per job)** | **applicable** | One graph per pipeline run, persisted to `output/artifacts/YYYY-MM-DD/graph.{db,json}`. |
| **Depth/TTL bounds on adapter recursion** | **applicable** | The current pipeline has no protection against an adapter re-trigger loop; if you adopt the trigger model you need the same depth bound. |

## 5. A concrete sketch of the lightweight version

Goal: replace the "throw everything into one cross_domain prompt" pattern
with "build a small graph from desk outputs, run ~5 deterministic and ~2
LLM adapters against it, materialize the digest from the graph." Don't use
LemonGraph or LemonGrenade.

### Minimum viable graph store

A new `morning_digest/graph.py` with ~150 lines:

```python
@dataclass
class Node:
    id: str          # e.g. "item:ai_tech-578f3df1...", "entity:OpenAI", "theme:AI-governance"
    kind: str        # "item" | "entity" | "theme" | "policy" | "region" | "outlet" | "seam"
    props: dict

@dataclass
class Edge:
    src: str; tgt: str; kind: str; props: dict

class DigestGraph:
    def add_item(self, item: dict) -> str: ...      # creates item: node + outlet/entity/theme/policy edges from connection_hooks
    def items_by_kind(self, kind) -> list[Node]: ...
    def neighbors(self, node_id, edge_kind=None) -> list[Node]: ...
    def items_sharing(self, hook_kind: str, min_count: int = 2) -> list[tuple[Node, list[Node]]]: ...
    def to_json(self) -> dict: ...                  # serialize for output/artifacts/YYYY-MM-DD/graph.json
```

No LMDB, no CFFI, no LMQL, no streaming queries. Plain dicts, indexed by
`kind` and by edge endpoints. 200 items × 5 hooks each = 1000 edges; a
Python dict handles this in microseconds.

### Minimum viable adapter / trigger model

A new `morning_digest/adapters.py`:

```python
class Adapter(Protocol):
    name: str
    def matches(self, graph: DigestGraph, since: int) -> list[Node]: ...
    def process(self, graph: DigestGraph, matched: list[Node]) -> list[Mutation]: ...
```

The runner is ~30 lines: while any adapter has new matches and depth < N,
call `process`, apply mutations, advance `graph.lastID`. Same control flow
as `CoordinatorBolt.execute` (`CoordinatorBolt.java:99-200`) without the
Storm bolt machinery.

`since` can be a simple integer counter incremented on each mutation —
that's the only piece of LemonGraph's log-position model worth keeping.

### First adapter migration: pick `seams`

`seams.run` is the worst offender for "graph reasoning shoved into one
prompt" and the easiest to decompose. Today
(`stages/seams.py:695-771`):

1. Build domain_summary from all desks, raw_summary from all RSS,
   transcript_summary — **one giant prompt**.
2. LLM produces per-item annotations.
3. `_validate_seam_annotations` (`:390-481`) hard-drops anything failing
   the evidence gate.

Decomposed onto the graph:

- **Node-loader adapter** (deterministic): every domain_analysis item
  becomes a `kind="item"` node. Each `connection_hook.entity/theme/policy`
  becomes a node + edge. Each `links[].url` registered domain becomes an
  `outlet` node + edge. Each `evidence` source on a candidate seam becomes
  an `evidence_source` edge. This subsumes `_links_by_item_id` (`seams.py:344-365`)
  and `_valid_item_ids` (`:332-341`).
- **Cross-outlet candidate adapter** (deterministic): query `items` that
  share ≥2 distinct outlets via `entity` or `theme` co-occurrence. This is
  *the same query* the cross_domain LLM currently does in its
  `cross_domain_connections` plan, except deterministic and exhaustive.
  Output: candidate `seam` nodes with `seam_type=selection_divergence`
  pre-tagged. Replaces a large chunk of `_normalize_seam_candidates`
  (`seams.py:236-329`).
- **Framing-divergence adapter** (LLM, narrow): for each candidate
  `seam` node with ≥2 attached `item` nodes that share a theme/entity,
  ask the LLM only "what's the framing disagreement here, in one line?"
  Prompt is ~10x smaller. This replaces the `framing_divergence` /
  `causal_divergence` / `magnitude_divergence` cases in the current
  `_VALID_SEAM_TYPES` (`:37-43`).
- **Evidence-gate adapter** (deterministic): exactly
  `_evidence_passes_gate` (`:373-387`) but expressed as
  `len(graph.neighbors(seam.id, "evidence_source")) >= 2`. Dropped seams
  are removed from the graph; the JSON artifact reflects what survived.
- **Source-cap adapter** (deterministic): replaces
  `_enforce_source_caps` (`assemble.py:110-146`) and
  `_cap_at_a_glance_items` (`cross_domain/parse.py:225-289`). Walks `outlet`
  edges, drops items that exceed `max_per_outlet`. Single source of truth
  instead of three.

Output artifacts (`seam_annotations.json`, `seam_candidates.json`,
`seam_data.json`) are generated by serializing the relevant graph
sub-views. Existing downstream consumers (`assemble.py`, `briefing_packet.py`)
keep working unchanged because the artifact contracts don't change.

### What it costs

- ~400 lines new code for `morning_digest/graph.py` + `adapters.py`.
- ~300 lines deleted from `seams.py` (most of `_normalize_seam_candidates`,
  `_validate_seam_annotations`, `_links_by_item_id`).
- One new artifact: `output/artifacts/YYYY-MM-DD/digest_graph.json`
  for inspection.
- Zero new system dependencies. Stays inside Docker as before.

## 6. Risks / what's misunderstood about the idea

### "Morning-Digest's data is graph-shaped"

Mostly yes, but watch the edges. Items relate via shared entities/themes/
outlets — that's a real graph. But desk items also have a *temporal*
dimension (today vs. yesterday, recurring vs. novel) that LemonGraph's
log-position abstraction doesn't capture cleanly because each daily run
gets its own graph. The "previous_cross_domain" context
(`stage.py:113`) is doing real work that would be awkward to model as
"prior graph diff."

### "LMDB will be fast"

Yes, and irrelevant. Bench numbers in `lemongraph/README.md` (1M nodes
inserted in 12s) are not the bottleneck for a pipeline whose total runtime
is dominated by ~10 LLM calls at 5–30s each. The graph layer overhead in
this design is sub-millisecond regardless of backing store.

### "Storm gives me parallelism"

`analyze_domain` already does desk-parallel via
`ThreadPoolExecutor(max_workers=4)` (`:975`). Storm/RabbitMQ buys nothing
for a 5-minute single-machine job. The LemonGrenade *idea* (adapters fire
when their query matches) is independent of Storm; the Java code just
happens to express it via Storm bolts.

### "I'll write Python adapters for LemonGrenade"

The Python adapter surface in LemonGrenade is anemic
(`/tmp/claude-1000/lemon/lemongrenade/core/src/main/java/lemongrenade/core/templates/LGAdapter.java`
is the canonical contract; Python adapters exist but the orchestrator
itself is Java/Storm). You'd be writing Python that talks RabbitMQ to a
JVM that talks LMDB. The host-side surface area is the operational
problem, not the language.

### "What about LemonGraph's REST API as a library?"

Possible but pointless. You'd run a separate process for ~50KB of data
that lives entirely in one Python pipeline run. Use a dict.

### Hidden complexity in trigger model

Current pipeline DAG is dead-simple: stages run in order, each reads
`context` and returns a dict. A trigger model (adapters fire when their
query matches new state) is more powerful but adds:
- termination conditions (depth/ttl, see `coordinator-api.txt:/api/job
  POST` — `depth: 4, ttl: 0`)
- ordering nondeterminism if two adapters match the same state
- replay-debugging cost: artifacts no longer have a clean per-stage path
  unless you explicitly log mutations.

For Morning-Digest's batch nature, **only adopt the trigger model where
you want incremental re-runs** (e.g., a late RSS feed produces new items
mid-pipeline). Otherwise stick with the static stage DAG and just use the
graph as a smarter context dict.

### Operational cost of LMDB / Mongo / Storm

Real numbers from the README install steps
(`/tmp/claude-1000/lemon/lemongrenade/README.md:25-100`): you'd add
RabbitMQ + Zookeeper + Storm + Mongo + supervisord to your Unraid box.
That's five new daemons and a JVM, at minimum. For a pipeline that
currently is "Python in Docker, run once a day." Categorically wrong scale.

## 7. Recommendation

**Don't adopt LemonGraph. Don't adopt LemonGrenade. Steal the pattern.**

### Concrete prototype path

1. **Write `morning_digest/graph.py`** (~150 lines) with `Node`/`Edge`/
   `DigestGraph`, indexed by kind and endpoints. JSON-serializable. Add
   tests for `items_sharing`, `neighbors`, `to_json`.
2. **Write `morning_digest/adapters.py`** (~80 lines) with the `Adapter`
   protocol and a runner that fires adapters until quiescence or depth-N.
3. **Refactor `seams` first** (per §5). Keep current `seams.py` as the
   regression target — produce identical
   `output/artifacts/.../seam_annotations.json` from the graph-based
   implementation. Compare 7 days of runs; only switch over once
   diff-clean.
4. **Move `_recompute_source_depth`, `_enforce_source_caps`,
   `_cap_at_a_glance_items` into adapters.** These are the deterministic
   patches to the LLM's output that are currently scattered across
   `assemble.py`, `cross_domain/parse.py`, and `analyze_domain.py`.
   Consolidating them gives one place to reason about source policy.
5. **Only then** consider whether `cross_domain` benefits from
   decomposition. The plan/execute LLM turns may still be the right
   abstraction for editorial voice — graph-driven adapters are good for
   *constraints*, not for *editorial judgment*.

### Lighter alternative (the actual recommendation)

If "graph as intermediate state" feels heavy, the lightest viable change
that captures most of the win is much smaller:

**Promote `connection_hooks` to an indexed lookup.** Build, in
`stages/cross_domain/`, an inverted index `{entity → [item_id]}`,
`{theme → [item_id]}`, `{policy → [item_id]}` from `domain_analysis`.
Pass that index into the cross_domain prompt *instead of*
the full desk dump. Two effects:

- The LLM sees structural co-occurrence directly and stops missing
  obvious cross-domain links.
- The deterministic adapters from §5 (cap, depth, gate) become trivial
  inverted-index lookups without any class hierarchy.

That's a half-day of work, doesn't require a graph library, doesn't
require an adapter framework, and captures most of the practical
benefit. **Start there.** If after a month of running it you find
yourself growing `cross_domain.py` to coordinate more index lookups, *then*
upgrade to the full graph + adapter design in §5. Not before.

The NSA repos remain useful as **reference reading for the pattern**
(read `HelloWorldAdapter.java:13-64` and `coordinator-api.txt` once),
not as dependencies. The whole Storm/RabbitMQ/Mongo/Mesos/Akka stack
is a 2017 bet on "scale to thousands of correlation jobs across a
cluster," and Morning-Digest is the wrong shape of problem for it.

## Appendix: LLM-vs-deterministic audit

Survey of stage prompts looking for work the LLM is asked to do that is
mechanical, then either re-done in code (override pattern) or only
incidentally enforced. Ordered by confidence. The `source_depth`
recomputation in `cross_domain/parse.py:452-465` cited in §3 is the
canonical example; everything below is in addition.

### HIGH

1. **`tag_label` emission in cross_domain output**
   - Location: `prompts/cross_domain_execute.md:48` schema requires
     `"tag_label": "human-readable label matching the tag"` per
     at-a-glance item.
   - Override: `cross_domain/parse.py:603` (`_validated_output`)
     unconditionally sets `item["tag_label"] = _TAG_LABELS.get(item["tag"], ...)`.
     Same dict is hard-coded again at `stages/assemble.py:37-50` and
     `cross_domain/parse.py:25-38`.
   - Cheaper: drop `tag_label` from the schema; assign in code from the
     `tag` field via the existing `_TAG_LABELS` map. Saves prompt tokens
     and removes a way for the LLM to drift the labels.

2. **`tag` normalization to the 12-value vocabulary**
   - Location: `prompts/cross_domain_execute.md:46` requires
     `"tag": "must be exactly one of: war, domestic, econ, ai, tech, defense, ..."`.
   - Override: `cross_domain/parse.py:602` calls `_normalize_tag`,
     which re-maps anything off-vocabulary via a 100-entry
     `_TAG_KEYWORDS` substring table (`parse.py:40-148`) and falls
     back to `"domestic"`. The `morning_digest/validate.py:228-231`
     path does the same fallback again.
   - Cheaper: don't ask the LLM for the tag at all. The desk
     each item came from already implies the tag set
     (`_DEFAULT_PRIMARY_DOMAIN_TAGS`, `parse.py:151-156`). For the
     ambiguous cases, run `_normalize_tag` on the headline once.

3. **`item_id` / `facts` / `analysis` "verbatim" copying**
   - Location: `prompts/cross_domain_execute.md:21,45` instruct the LLM
     to "Preserve domain analysts' `item_id`, `facts`, and `analysis`
     verbatim in `at_a_glance`". The LLM is also told to copy `item_id`
     exactly in `prompts/seam_annotations.md:10`.
   - Override / use: nothing immediately rewrites these in the
     cross_domain path, but the field is purely ID-plumbing — by the
     time cross_domain runs, every domain item has a
     `_stable_item_id` (`analyze_domain.py:572-593`) hash. Asking the
     LLM to retype it is a known failure mode (typos drop items via
     `seams.py:251-252` "dropping candidate for unknown item_id").
   - Cheaper: the LLM should emit a *selection* (list of item_ids it
     wants in at_a_glance and which order) and a `cross_domain_note`
     per selection. Code joins the selection back to
     `domain_analysis[*]["items"]` by ID and copies `facts`/`analysis`
     deterministically. This eliminates an entire class of "LLM
     mangled the verbatim copy" diagnostics.

4. **Seam annotation `links` field**
   - Location: `prompts/seam_annotations.md` schema; `links` are
     attached per-annotation in the artifact.
   - Override: `seams.py:344-365` (`_links_by_item_id`) builds the
     authoritative map from `domain_analysis`; `seams.py:444` writes it
     in regardless of what the LLM produced.
   - Cheaper: already correct deterministically. Documentation
     cleanup — the prompt should not imply LLM-supplied evidence
     URLs are kept.

5. **"Exactly N" quotas in cross_domain plan**
   - Location: `prompts/cross_domain_plan.md:16,20,28` require
     `cross_domain_connections`, `deep_dives`, and `worth_reading` to
     be returned in *exact* counts. The plan turn explicitly templates
     `${connection_count}`, `${deep_dive_count}`, `${worth_reading_count}`.
   - Override: `cross_domain/parse.py:413-419` (`_normalize_cross_domain_plan`)
     truncates each list to the configured count regardless of what
     the LLM produced. Underproduction is silently accepted.
   - Cheaper: relax the prompt to "up to N" and let the truncation
     in code be the cap. The "exactly" wording wastes attention and
     overconstrains low-evidence days where 1 connection is more
     honest than 3.

6. **Cross-domain seam `linked_item_ids ≥ 2` rule**
   - Location: `prompts/seam_annotations.md` and the prompt for
     plan/execute imply that cross_desk items must link two items.
   - Override: `seams.py:309` and `seams.py:461` both drop entries
     where `len(linked_ids) < 2`, plus they intersect with the valid
     `_valid_item_ids` set. Two layers.
   - Cheaper: the cross-desk linking is the canonical graph query
     ("two items sharing an entity/theme hook from different desks")
     §5 already proposes — compute candidates from
     `connection_hooks` and let the LLM only write the `one_line`
     framing for surviving pairs.

7. **Seam annotation evidence gate (≥2 distinct sources, ≥2 useful excerpts)**
   - Location: `prompts/seam_annotations.md:31-36` ("Hard evidence gate").
   - Override: `seams.py:373-387` (`_evidence_passes_gate`) drops
     anything that fails. Same rule expressed twice.
   - Cheaper: keep the prompt-side gate as a hint, but recognize the
     code is the source of truth. Could be a graph constraint per §5.
     (Already cited in §3; included here for completeness.)

8. **Per-outlet cap enforcement (three implementations)**
   - Location: implicit in the cross_domain plan/execute prompts as
     "diversity" guidance.
   - Override: `cross_domain/parse.py:225-289` (`_cap_at_a_glance_items`),
     `stages/assemble.py:110-146` (`_enforce_source_caps`), and
     `analyze_domain.py:827-849` (`max_category_share`). Three
     enforcement layers for "don't oversample one outlet."
   - Cheaper: collapse to one (assemble), drop the LLM-side
     "diversity" wording. Already cited in §3 #3.

### MEDIUM

9. **`coverage_gaps` "Maximum 5 gaps" cap**
   - Location: `prompts/coverage_gaps.md:34` ("Maximum 5 gaps").
   - Override: `stages/coverage_gaps.py:155` (`if len(gaps) >= 5: break`)
     truncates regardless. The prompt cap is decorative.
   - Cheaper: remove the prompt-side number; let code be the limit.
     Saves nothing big but matches the pattern.

10. **`per_item` annotations capped at 6 in two places**
    - Location: `prompts/seam_annotations.md:69` ("Return at most 6
      `per_item` annotations") + `_DEFAULT_SEAMS_CFG["max_per_item_annotations"]`
      (`seams.py:48`).
    - Override: `seams.py:471-479` sorts by confidence and truncates.
      `assemble.py:149-184` then collapses to one annotation per item
      regardless. The "6 max" is already reduced to "1 per item" by
      assemble, so the prompt cap is the wrong knob.
    - Cheaper: remove the prompt-side cap entirely; the per-item
      collapse in assemble is the real constraint. The LLM is being
      asked to plan a budget that two later layers override.

11. **`_ensure_primary_glance_coverage` re-injects missing primary tags**
    - Location: `prompts/cross_domain_plan.md:9-12` and
      `cross_domain_execute.md:17-20` instruct the LLM to "ensure
      geopolitics/war, AI/agentic tech, and defense/space each have
      at least one item."
    - Override: `cross_domain/parse.py:318-352` re-injects a
      best-available primary item if the LLM dropped one. Already
      cited in §3 as the canonical fix-up.
    - Cheaper: per §5, run the coverage check as a deterministic
      adapter against the desk-tag map, then ask the LLM only to
      *order* the resulting set. The selection problem is what the
      LLM is bad at; the ordering/voicing is what it's good at.

12. **`domains_bridged` on deep dives**
    - Location: `prompts/cross_domain_execute.md:64` schema requires
      each deep dive to emit `"domains_bridged": ["geopolitics_events", ...]`.
    - Override: nothing currently validates this — but the value is
      mechanically derivable from which desks contributed the
      `further_reading` URLs (or which desks the dive's source items
      came from). `stages/anomaly.py:218-220` consumes it without
      checking honesty.
    - Cheaper: derive from `further_reading` link → desk lookup
      after the LLM picks a dive. One join, no LLM tokens spent on
      ID metadata.

13. **`analyze_domain` "merge multiple sources covering the same event into ONE item"**
    - Location: `prompts/analyze_domain_system.md` via `_SHARED_RULES`
      (`analyze_domain.py:486`): "Multiple sources covering the same
      event: merge into ONE item with all relevant links."
    - No override exists. The LLM is asked to deduplicate, and it
      mostly does, but there's no safety net — duplicates that slip
      through propagate all the way to `at_a_glance`.
    - Cheaper: a URL-hash + title-trigram pre-merge would catch the
      easy cases before the LLM runs, and a post-LLM check could
      flag suspected duplicates. This is also the "items_sharing"
      query from §5.

14. **`source_depth` per-item label in `analyze_domain`**
    - Location: `prompts/analyze_domain_system.md` schema
      (`analyze_domain.py:405`) asks each item to label itself
      `single-source | corroborated | widely-reported` based on a
      counted-domains rule.
    - Override: `cross_domain/parse.py:452-465` (`_recompute_source_depth`)
      counts distinct registered domains and overrides — the same
      finding §3 already calls out, but worth noting it originates
      one stage earlier in `analyze_domain`. The LLM is asked to do
      the count *twice* (once at desk time, once at editor time),
      and code overrides both.
    - Cheaper: drop `source_depth` from the desk schema entirely;
      it's a cheap function of `links` and can be computed on read.

### LOW

15. **`compress.py` "target ~N words"**
    - Location: `stages/compress.py:36-41` asks the LLM to match a
      `_target_words` (`:23-26`) count; fallback at `:56-59` truncates
      to N words on empty output but nothing re-clips an over-long
      compression.
    - Cheaper: tell the LLM "be concise" and post-clip in code, or
      accept length is judgment-based and stop passing the number.

### Summary
15 findings (8 HIGH, 6 MEDIUM, 1 LOW). The `tag` / `tag_label` /
verbatim-copy / quota cluster (#1–#5) are the cheapest wins: pure
prompt-token waste with deterministic overrides already in place.
The seam evidence gate (#7) and primary-coverage re-injection
(#11) are the most architecturally interesting — graph-shaped
queries pretending to be prompt rules, which §5's adapter sketch
handles naturally.

## Appendix B: Graph utility across the rest of the pipeline

The main doc argued that seams/cross_domain has the strongest case for graph-shaped intermediate state. This appendix surveys the rest of the pipeline — collect, enrich, prepare_*, anomaly, coverage_gaps, briefing_packet, assemble — and asks the same question without assuming the answer. Calibration: the user runs this pipeline once a day, alone. Complexity must be earned. WIN/MAYBE/NO is decided by whether *current code is visibly straining* against tree/list assumptions, not by whether a graph would be theoretically tidier.

### B.1 Article dedup / "everyone is reporting the same wire story" — **WIN**

The only dedup that exists today is `_dedup_by_url` in `stages/enrich_articles/scheduling.py:60-69` — pure URL-string equality. Same-event-different-outlet collapse is delegated entirely to the LLM by a single line in the desk prompt: `analyze_domain.py:486` ("Multiple sources covering the same event: merge into ONE item with all relevant links"). Appendix item #13 already flags this as having no safety net. Local-news has its own one-off `_WIRE_MARKERS` heuristic at `prepare_local.py:16-22` (PRNewswire/BusinessWire/GlobeNewswire) but it only tags press releases, not actual wire-story duplicates across outlets. The data is graph-shaped: nodes = articles, edges = "shares URL canonical form" / "shares ≥3 title trigrams" / "shares lede sentence" / "shares headline named-entities." Connected components = a story. The current pipeline has no such structure, so a Reuters→AP→local-newspaper triple all surfaces as three independent items, three times the source-depth credit, and three slots burned.

*Sketch:* a pre-LLM `cluster_articles` pass over `raw_sources["rss"]`. Nodes = articles by URL. Edges = title-shingle-Jaccard ≥ T. Emit `cluster_id` per article so `analyze_domain` sees `[cluster_id=C12, items=[reuters/.../iran-strike, ap/.../iran-strike, hjnews/.../iran-strike]]` and the LLM picks one canonical with `links=[all three]` deterministically. The same `cluster_id` then feeds `_recompute_source_depth` (`cross_domain/parse.py:452-465`) so source-depth becomes a function of *distinct clusters*, not distinct domains, killing the Reuters-syndicated-by-AP false-corroboration class. Roughly 80 lines, no new deps (rapidfuzz or stdlib `difflib.SequenceMatcher`).

### B.2 Cross-day continuity (entities/themes spanning multiple briefings) — **MAYBE**

Cross-day memory today is anemic and scattered:
- `cross_domain` loads only the previous day's `cross_domain_output` via `pipeline.py:143-152` and passes it as a single text block in `cross_domain/prompt.py:39-71` — "yesterday's headlines" as raw text, not as structured continuity.
- `coverage_gaps` keeps a separate JSONL history at `output/coverage_gaps_history.jsonl` (`coverage_gaps.py:29, 62-104`) and inlines the last 15 gap topics as text in the prompt (`_build_recurring_context`).
- `anomaly` reads 7 days of `digest_json` solely to compute item-count averages (`anomaly.py:275-282`).

There is no entity-level continuity ("Iran has appeared 5 days running"), no story tracking ("the Hormuz incident has been live since 04-26"), no thread-of-themes view. The LLM is asked to do this implicitly off a single prior day's text. A graph keyed on `(entity, theme, region)` with `mentioned_on=[date,date,...]` properties would answer "what's ongoing" and "what's new today" deterministically.

The reason this is MAYBE rather than WIN: the user hasn't asked for continuity features, and the current "yesterday's text in the prompt" actually works passably. Building cross-day infra without a confirmed editorial use ("show me a 'this story is on day 3' badge"; "warn me when an entity drops out of view after 5 days") is speculative. The substrate is interesting; the demand isn't proven.

*If pursued:* a daily `output/continuity_graph.json` storing `{entity → [(date, item_id, headline)], theme → ..., region → ...}` rolled forward from today's `connection_hooks`, with a 14-day TTL on edges. `cross_domain` and `coverage_gaps` then read structured continuity instead of text snippets.

### B.3 Calendar / weather / local-event linking — **NO**

The calendar/weather/local stages are pure data flatteners. `prepare_calendar.py:44-91` concatenates holidays + church_events + economic_calendar + launches and sorts by date. `prepare_weather.py` is 33 lines of pass-through. `prepare_local.py:47-74` filters by category and runs a wire-marker check. The assembled briefing renders these as *parallel tracks* — week_ahead block, weather block, local block — with no editorial linkage between them. There is no current code attempting "outdoor event tomorrow ↔ weather forecast ↔ road-closure article" connections. Building that linkage as a graph would be inventing a feature, not formalizing one. The user's locale (Cache Valley, single-person digest) genuinely doesn't need it: the events list is 5 items, the weather is one paragraph, local news is 4 items. Cross-linking that volume by hand at read-time costs less attention than maintaining the linker. Skip.

### B.4 Spiritual pipeline (verses, themes, cross-references) — **NO**

`prepare_spiritual_weekly.py` builds a `daily_units` list keyed by id (`spiritual_units.py:39-89`) with `kind ∈ {narrative_unit, key_scripture, misuse_correction, scholarly_insight, language_context, faithful_application}` and a `proposed_sequence` mapping weekday → unit_id (`prepare_spiritual_weekly.py:209-222`). `prepare_spiritual.py:75-94` selects the day's unit. The structure is already a small DAG (units have `anchor_ref`, `source_refs`), but it's *one week wide* — 6 units, deterministic mapping, sequential rendering. The LLM produces the weekly artifact once per week from a user-authored markdown guide; the daily stage is a lookup. Scripture cross-references *do* form a graph in the abstract, but the pipeline never traverses them and the user explicitly does not want LLM-generated daily reflections (`prepare_spiritual.py:1-12` docstring: "no longer asks the LLM to improvise"). Adding cross-reference graph machinery would be invention, not formalization. Skip.

### B.5 Geographic / topical hierarchies — **NO** (with a caveat)

`analyze_domain.py:406` already emits `connection_hooks[*].region` per item ("geographic region or 'global'"), and `seams.py:137-143` includes `region` in the formatted hook string fed to the seams prompt. But `region` is *only* string-decoration: nothing in the pipeline groups by region, rolls up to country→region, or queries "what's the dominant Asia-Pacific theme today." The hierarchy is implicit and unused.

This is NO because: the *use case* for geographic rollup isn't present. No stage asks "give me items by region," no template renders a regional view, anomaly checks don't compare regional balance. Adding a region hierarchy is a feature waiting for a request.

*Caveat:* if the user ever wants a "world map" or "Asia/Europe/Americas at a glance" view, region edges in the unified entity graph (see §B.8) make it a one-line query. Until then, leaving `region` as a flat string is correct.

### B.6 Anomaly / coverage_gaps as graph queries — **MAYBE**

`anomaly.py` has five checks (`:443-463`); three of them are already graph queries in disguise:
- `_check_category_skew` (`:64-77`): "primary tags missing from at_a_glance" = `for tag in primary: assert any(item.tag == tag)`.
- `_check_source_absence` (`:104-207`): walks `raw_sources` and `domain_analysis`, builds two `{category → {domains}}` maps, asks "raw category had ≥3 items but no overlap with covered domains" — this is *literally* a left-anti-join expressed as imperative dict-of-set traversal.
- `_check_unusual_deep_dives` (`:235-268`): checks `tag ∈ primary` over deep_dives, with fallback to `domains_bridged` and a keyword scan — three layers of "does this dive cover any node connected to a primary-tag desk."

`coverage_gaps.py` is more LLM-driven (it asks the model "what's missing") but `_load_recent_history` + `_build_recurring_context` (`:62-104`) is the same shape: text-glued history fed back into a prompt because there's no graph to query.

Why MAYBE not WIN: each check is 30-50 lines of legible Python; they work; rewriting them as graph queries trades clear imperative code for a query layer that only saves lines if you have ≥4 such queries. Today there are 3. If the trigger model from §5 happens, anomaly+coverage_gaps fold into it naturally as deterministic adapters; if it doesn't, leave these alone.

### B.7 Briefing assembly cross-references — **NO**

`assemble.py:404-427` produces a flat dict-of-lists `template_data` with parallel sections (`at_a_glance`, `deep_dives`, `worth_reading`, `contested_narratives`, `coverage_gaps`, `local_items`, `regional_items`, `week_ahead`). `briefing_packet.py:192-204` does the same for the chat-context packet. `_select_inline_seam_annotations` (`assemble.py:149-184`) is the *only* cross-section reference: it attaches one seam annotation to each at_a_glance item by `item_id`. That's a single join, not a graph traversal — and it's already 35 readable lines. The briefing is genuinely tree-shaped: one digest, N sections, M items per section, no inter-section dependencies that would benefit from graph queries. The Phase 1 vs Phase 3 fork (`assemble.py:317-346`) is a presentation toggle, not a graph problem. Skip.

### B.8 Source overlap / source health — **NO**

`scripts/source_health.py:66-195` computes per-feed health from a 14-day window of artifacts, classifies feeds into `{active, low_frequency, headline_radar, enrichment_required, degraded, broken}`, and writes one `source_health.json` per run. The data model is one row per feed with rolling metrics (`items, median_chars, empty_rate, success_rate, fallback_rate, http_error_rate, paywall_rate, last_nonempty_date`). It's a *table*, not a graph. There's no edge to model — feeds don't relate to each other in a way the pipeline cares about; what matters is per-feed time series. `audit_rss_quality.py` is the same shape (`:25-80`). Source diversity for a single article *is* graphy (article → outlets), but that belongs in the dedup graph (§B.1), not in source_health. Skip.

### Ranked top WINs (value per effort)

1. **Article dedup graph (§B.1)** — solves a concrete bug (Reuters/AP/local triplication of one story), feeds directly into `_recompute_source_depth` so the LLM stops getting falsely-corroborated source counts, ~80 lines, zero new deps. **Highest value-per-effort by a wide margin.** This is the only one I'd build before being asked.
2. **Continuity graph (§B.2)** — only worth building if the user wants a "story on day N" / "ongoing thread" feature. Ask first. If yes, the substrate is ~150 lines and unlocks several editorial features at once.
3. **Anomaly/coverage_gaps as deterministic adapters (§B.6)** — only worth doing if §5's adapter framework already exists for seams/cross_domain. Don't build the framework for this alone; fold these in once the framework exists.

Everything else (calendar linking, spiritual cross-refs, geographic hierarchies, briefing cross-refs, source-health graph) is NO. The data isn't graph-shaped, the use case isn't present, or the current code doesn't strain.

### Cross-cutting observation: one graph, or many?

There is **one** unified entity-and-story graph that ties §B.1, §B.2, §5, and §B.5 together. Nodes: `article`, `cluster` (a same-event group of articles), `entity`, `theme`, `region`, `policy`, `outlet`. Edges: `article–[in_cluster]→cluster`, `article–[from_outlet]→outlet`, `article–[mentions]→entity/theme/region/policy`, `cluster–[seen_on]→date`. §B.1's dedup is "build clusters." §B.2's continuity is "for each entity/theme node, list its `seen_on` dates." §5's seam detection is "find clusters whose linked items came from outlets in different desks with framing-divergence evidence." §B.5's region rollup is a single neighbor query. The same graph, materialized once per run from `raw_sources` + `connection_hooks` and rolled forward across days for the entity/theme nodes only, serves all four. The seams-graph from §5 and the dedup-graph from §B.1 are the *same graph*, just with different adapters reading different slices. That argues for building §B.1 first as the foundation, then §5's adapters on top, then opt-in continuity (§B.2). Anomaly/coverage_gaps (§B.6) get added as adapters last. Calendar, spiritual, source_health stay outside the graph — they're genuinely tabular and trying to graph-ify them would dilute the model.

## Appendix C: Lightweight per-day RAG / embeddings

### Framing

By "per-day RAG database" the user means: at run start, embed today's articles (titles + summaries) into vectors, hold them in an in-process index (numpy cosine matrix, FAISS-flat, or hnswlib), let downstream stages issue similarity queries against it, throw the index away when the run ends. No persistent vector DB, no cross-day store, no migrations. Calling that a "RAG database" is generous — it's an embedding matrix with a `search(query) -> top_k` method. The honest size: 215 RSS items in `raw_sources.json` for 2026-05-01 (`output/artifacts/2026-05-01/raw_sources.json`, counted via `len(d["rss"])`); 51 desk items in `domain_analysis.json` across 7 desks. A 215×384 float32 matrix is 330 KB. A pairwise cosine-similarity matrix is 215×215 = 46k floats = 180 KB. There is no scaling problem to solve.

The honest comparison is to §B.1's title-shingle Jaccard clustering. Title-shingle Jaccard catches lexical near-duplicates: `"US to withdraw 5,000 troops from Germany in dispute over Iran conflict"` (Reuters) vs `"US said to be withdrawing 5,000 troops from Germany over Iran war spat"` (likely AP rewrite) — both real titles in the 2026-05-01 raw feed. Embeddings catch *semantic* overlap where lexical overlap is low: `"Houthi missile strike on Red Sea tanker"` ≈ `"Yemen attacks shipping near Bab el-Mandeb"`. The question for this codebase is whether the semantic gap §B.1 misses is large enough — given the news items actually in the pipeline — to justify the dependency, embedding API spend, and second similarity system.

### Verdict

**MAYBE — and only as a small bolt-on to the §B.1 graph, not as its own subsystem. Build §B.1 first; add embeddings as a `semantic_similarity` edge type only if the lexical-only graph visibly misses pairs in real runs.** A standalone "per-day RAG" with retrieval against prompts is cargo-cult here: prompts are not overflowing (`domain_analysis.json` is ~26k tokens, well under the 12k–16k `max_tokens` *output* limit at `config/pipeline.yaml:43,77` and far under any modern context window), and the LLM already does in-context similarity over the desk dump. The only place embeddings earn their keep is as a *deterministic* signal feeding the same dedup/seam graph §B.1 builds.

### Where it would actually plug in

Three candidate sites, ranked by usefulness:

1. **`stages/enrich_articles` or a new `stages/cluster_articles` pre-pass — strongest case.** Take `raw_sources["rss"]` (215 items), embed `title + summary[:500]`, build a pairwise cosine matrix once, emit `cluster_id` per item using single-link clustering at threshold ≥0.82 over the *combined* edge set: `(jaccard(title_shingles) ≥ T) OR (cosine(embed) ≥ 0.82)`. The cluster_id then flows exactly as §B.1 already proposes — into `analyze_domain`'s "merge into ONE item" rule (`stages/analyze_domain.py:486`) and into `_recompute_source_depth` (`cross_domain/parse.py:452-465`). Input: list of `{url, title, summary}`. Output: per-article `cluster_id`. This is the only stage where embeddings produce a signal the LLM is structurally bad at — the LLM never sees all 215 raw items at once, so it cannot detect cross-feed wire-story duplication; today only `analyze_domain` performs that merge, and only within a desk's slice (`_DOMAIN_CONFIGS`, `analyze_domain.py:63-388`).

2. **`stages/seams.py` cross-desk candidate query — secondary case.** §B.1 / §5 already proposes "items sharing ≥1 entity hook" (`connection_hooks`, `analyze_domain.py:406`) as the deterministic candidate generator for cross-desk seams. Empirically, the 2026-05-01 run produces 8 entities shared across ≥2 desks (e.g. `openai → {ai_tech, defense_space}`, `nato → {culture_structural, energy_materials, geopolitics_events}`). That hook-based query is *already* sufficient to seed candidates. Embeddings on top would catch pairs where the hooks were extracted differently (`"OpenAI"` vs `"Sam Altman"`, `"DoD"` vs `"Pentagon"`) — a long-tail recall improvement of maybe 10–20% over the hook-join. Input: per-desk-item embedding. Output: candidate seam pairs whose hooks didn't match but cosine ≥ 0.78. Worth adding only after §5's hook-join adapter exists and is observably under-recalling.

3. **`stages/coverage_gaps.py` recurrence detection — tertiary, weak case.** Today `_load_recent_history` + `_build_recurring_context` (`stages/coverage_gaps.py:62-104`) glues 15 prior gap topics into the prompt as text. An embedding similarity check between today's candidate gaps and historical gaps would let "this gap is the same as one flagged 4 days ago" be a deterministic signal rather than something the LLM infers from the text dump. But this requires *carrying yesterday's index forward* — i.e., not "per-day ephemeral." If the user truly wants per-day-only, this use case dies. Skip unless §B.2 continuity is built.

### What it adds beyond §B.1

I tried to construct compelling pairs from the 2026-05-01 data where lexical-only Jaccard fails and embeddings would catch the link. Two examples surfaced:

- **`"Hezbollah's fibre-optic drones pose new challenge for Israel"` vs `"Iran's drone arsenal and Lebanese proxies"` (hypothetical sibling article).** Title-shingle Jaccard on 3-grams here is ~0.05 (almost no shared tokens). Embeddings would put them in the same neighborhood (~0.74 cosine on a MiniLM model). But these are *related coverage*, not the *same wire story* — collapsing them under one `cluster_id` would be wrong. The right machinery for "related but distinct" is a `semantic_neighbor` edge, not a cluster merge. So even when embeddings find a pair Jaccard misses, the right answer is usually a softer edge type, not stronger dedup.

- **`"Trump's Iran war leaves US with sharpest fuel shock in G7"` (defense_space-ish framing, actually appears under econ-adjacent) vs `"Iran's Currency Crisis Deepens as War Batters Economy"` (econ).** These would share `connection_hooks` (`Iran`, `war`, `economy`) and so `§B.1 / §5`'s hook-join already catches the cross-desk pairing. Embeddings add nothing here.

Honest finding: in 2026-05-01's data, I could not construct a pair where embeddings beat the *combination* of §B.1's title-shingle Jaccard *and* §5's `connection_hooks` co-occurrence query. The hook extractor already produces a semantic signal — that's the whole point of `entity/theme/policy/region` — and the LLM is doing the embedding work upstream when it generates hooks. Embeddings would mostly re-derive what `connection_hooks` already encode.

### What it doesn't help

- **Prompt size.** Not the bottleneck. `domain_analysis.json` ≈ 26k tokens; `cross_domain` plan/execute prompts assemble desk outputs that fit comfortably in modern Fireworks Kimi K2 / MiniMax M2 context windows used at `config/pipeline.yaml:42,76`. There is no overflow to retrieve around.
- **Editorial voice / framing-divergence detection.** That's `seams.py`'s LLM-side work; similarity scores don't substitute for "what's the framing disagreement here, in one line."
- **Anomaly checks (`stages/anomaly.py`).** These are category-balance and source-absence queries; embeddings don't help with quota arithmetic.
- **Calendar / weather / spiritual / local-items.** All NO from §B.3–B.4. Nothing to retrieve.
- **Cross-day continuity.** Per-day ephemeral by definition kills this. If you want continuity, you need §B.2's persistent entity graph with `seen_on` dates — embeddings don't substitute for that.

### Operational cost

Two paths, both cheap, both with caveats:

- **Hosted (Fireworks `/v1/embeddings`).** Pipeline already speaks Fireworks (`morning_digest/llm.py:34`, base_url `https://api.fireworks.ai/inference/v1`). One extra HTTP call per run, batched: 215 items × ~150 tokens = ~32k tokens per run. At Fireworks BGE / Nomic embedding pricing this is fractions of a cent per run. Adds an external dependency (network, API key already exists), but no Docker image weight. **Recommended path if embeddings happen.**
- **Local sentence-transformers (MiniLM-L6-v2).** ~90 MB model + ~500 MB PyTorch in the Docker image. CPU runtime on 215 short items: ~3–8 seconds on a modest x86 box. No network call, fully offline. The cost is image bloat (current image is `python:3.12-slim` per `Dockerfile:1` plus crawl4ai); adding torch roughly triples it. Probably not worth it for a single-user daily pipeline.
- **Index structure.** 215 vectors. Use `numpy.dot(M, M.T)` for the pairwise matrix or `scipy.spatial.distance.cdist`. Don't introduce FAISS/chroma/hnswlib — for ≤500 items they're slower than numpy due to setup overhead and add real dependency weight. *Calling the result a "RAG database" oversells the architecture.* It's a 215×384 numpy array.

### Recommendation

**Don't build a "per-day RAG database" as a standalone subsystem. Do consider a `semantic_similarity` edge in §B.1's article-dedup graph, but only after §B.1 ships and you observe it missing real wire-story pairs.**

Concrete sequencing:

1. Build §B.1 (title-shingle Jaccard clustering) as proposed. ~80 lines, no new deps. Run it for 2 weeks. Inspect `output/artifacts/*/cluster_log.json` (a new diagnostic artifact) for false-negatives — pairs that should have clustered but didn't because lexical overlap was too low.
2. **Only if** that audit shows ≥5 false-negatives per week of clusters that would have been caught by semantic similarity, *then* add a Fireworks `/v1/embeddings` call to `cluster_articles` and union the two edge sets at thresholds (Jaccard ≥ 0.4 OR cosine ≥ 0.82). ~30 additional lines, one new HTTP call per run, no new dependency.
3. Never build a "retrieval-into-prompt" abstraction. The prompts aren't overflowing and the LLM's in-context similarity is already doing the work that retrieval would automate. Adding retrieval here is solving a problem the pipeline doesn't have.
4. If §B.2 continuity is later pursued, embeddings of *entity descriptions* (rolled forward across days) become a natural fit for "is today's `Iran` the same `Iran` node as yesterday's." That's a different system from the per-day index and should be designed then, not now.

The buzzword path — "add a vector DB, retrieve top-k articles into every prompt" — is the cargo-cult version. The earned-its-keep path is one optional edge type in a graph that already has a more important edge type. Build the more important edge type first.

## Appendix D: Architectural inspiration from Intelligence Community software & tradecraft

### Framing

The IC has spent decades on the exact problem Morning-Digest solves at hobby
scale: fuse multi-source open material into a daily product with calibrated
claims, sourcing, and judgment. The literature is large, mostly
public, and mostly *not* worth importing as software — DCGS-class systems,
Storm/RabbitMQ orchestrators, classification-marking pipelines, and
multi-INT taxonomies all assume a battalion, not a person, and the same is
true for OpenCTI/MISP/STIX wire formats. **The IC concepts that matter at
this scale are tradecraft, not infrastructure**: calibrated estimative
language, BLUF/tearline structure, sourcing tiers, structured analytic
techniques (ACH, key-assumptions check, devil's advocate), and explicit
Priority Intelligence Requirements. Each of those is small (tens to a few
hundred lines) and slots onto a stage that already exists. The big-system
inspirations are NiFi-style provenance (already partially present in
artifacts), Sigma/YARA-style declarative rules (a reasonable fit for
`anomaly.py`), and the *workflow* idioms of link-analysis tools like
Maltego (UI-only — irrelevant here). Most of this appendix says SKIP or
ADAPT; the WINs are concentrated in §D.3.

This appendix deliberately does not re-derive ground covered earlier. Graph
substrate is Appendix B; per-day embeddings are Appendix C; the
LLM-vs-deterministic audit is the first appendix. The discipline applied
to those — say NO when the data isn't shaped for it, say WIN only when the
current code visibly strains — is applied here too.

### D.1 Note on what was already inspected

To avoid asserting things about code I didn't read, the verdicts below cite
specific files and lines. The pipeline today is:
`collect → enrich_articles → compress → analyze_domain → seams →
cross_domain (plan→execute) → coverage_gaps → assemble → anomaly →
briefing_packet → send`
(`config/pipeline.yaml:16-97`). The desks are seven topical analyst passes
(`config/pipeline.yaml:98-148`, `stages/analyze_domain.py:63-388`). Sourcing
already has a 2-tier `reliability` field per feed
(`config/sources.yaml:45,77,254` — `primary-reporting`,
`analysis-opinion`, `institutional-analysis`) which is surfaced into desk
prompts as a bracketed annotation
(`stages/analyze_domain.py:514-515`, `stages/seams.py:173-174`) but is
*not* propagated downstream into cross_domain or assemble. Hedging
discipline is already partially encoded in `analyze_domain`'s
`_SHARED_RULES` (`stages/analyze_domain.py:452-454`) and
`cross_domain_system.md:9-11`, and a regex blocks four hedged seam openings
(`stages/assemble.py:52-56,161-164`). No stage today emits a numeric or
labeled confidence band; `seam_annotations` has the only structured
confidence field (`high|medium|low`, `prompts/seam_annotations.md:18`).
There is no PIR config — interest priorities are hardcoded as the literal
strings "war", "ai", "defense" in three places
(`config/pipeline.yaml:205-208,219-222`, `cross_domain/parse.py:150`) and as
keyword lists in `anomaly.py:43-48` and `cross_domain/parse.py:40-148`.
There is no devil's-advocate stage; `seams.py` does adversarial review on
*facts* (framing/causal/magnitude divergence between sources) but never
attacks today's draft. There is no I&W register beyond `coverage_gaps`'
implicit "what's missing" prompt.

### D.2 Software-architecture patterns

#### Apache NiFi (NSA Niagarafiles) — provenance — **ADAPT, partial**

NiFi's load-bearing idea is **per-record provenance**: every flowfile
carries a lineage of every processor that touched it, with timestamps and
attributes, queryable end-to-end. Morning-Digest already does a folk
version of this — the run writes per-stage artifacts to
`output/artifacts/YYYY-MM-DD/*.json` and `enrich_articles.json` records
per-item provenance/status/tier/before-after lengths
(`CLAUDE.md` enrichment notes; `stages/enrich_articles/`). The gap is
**audit at the briefing edge**: nothing today verifies that every
factual claim that lands in `digest_json["at_a_glance"][*].facts`,
`digest_json["deep_dives"][*].body`, or
`digest_json["worth_reading"][*].description` is supported by a URL that
appears in `raw_sources` *and* survived `_validated_output`'s `url_known`
filter (`cross_domain/parse.py:599-629`). That filter does its job at the
links level, but a deep-dive *body paragraph* can assert "Iran reportedly
struck a tanker" with no surviving link to evidence — the body is opaque
to the URL audit. **Verdict: ADAPT** — write a 50-line
`stages/audit_provenance.py` post-pass that scans deep-dive bodies for
proper-noun claims (NER-lite, regex on capitalized 2+ word spans) and
flags any unanchored claim, similar to the `_downgrade_overlap_depth`
pattern at `cross_domain/parse.py:522-582`. Don't import NiFi itself —
the NSA repo is JVM/Storm machinery and the gap here is one missing
audit, not a flow framework.

#### Apache Metron / Spot — security analytics pipelines — **SKIP**

Both are batch pipelines for SIEM-style telemetry: ingest → parse →
enrich → score → store. Morning-Digest is already this shape
(`config/pipeline.yaml:16-97`). The interesting Metron primitives —
threat intel feed integration, Stellar-the-DSL, Storm topology — solve
SOC-scale problems Morning-Digest doesn't have. SKIP.

#### STIX 2.1 data model — **ADAPT one idea, SKIP the wire format**

STIX is a JSON schema for cyber-threat info: SDOs (campaign, threat-actor,
malware, indicator), SROs (`uses`, `targets`, `attributed-to`),
sightings, confidence, kill-chain phases. The wire format is irrelevant
here — we are not exchanging with TAXII servers. The *one* idea worth
stealing is **typed relationships as first-class objects with their own
properties** (confidence, first-seen, last-seen). Morning-Digest's
`connection_hooks` (`stages/analyze_domain.py:406`) and
`cross_domain_connections` (`prompts/cross_domain_system.md:67-73`,
`prompts/cross_domain_plan.md:39-47`) are already trying to be SROs but
they're stored as untyped string blobs inside item dicts. The Appendix
B.1+B.2 graph substrate is the right place for this — when (if) that
graph is built, give edges typed predicates (`mentions`, `targets`,
`opposes`, `funded_by`, `regulates`) drawn from a small vocabulary
rather than free-form `theme` strings. **Don't import STIX schemas.**
A 20-entry vocabulary of edge types beats a 200-entry STIX taxonomy at
this scale; STIX's surface area is the wrong tradeoff for one user.

#### Sigma / YARA — pattern-as-rule — **APPLY**

Sigma rules are YAML-encoded detection patterns (logsource + selection +
condition); YARA rules are byte-pattern matches with metadata. The
load-bearing idea is **declarative, versioned, reviewable rules** stored
as files separate from code. `anomaly.py` is structurally a Sigma
ruleset written as imperative Python: five hardcoded checks
(`stages/anomaly.py:443-463`) with parameters scattered through
`config/pipeline.yaml:218-257` and code constants
(`stages/anomaly.py:26-48`). It works, but adding a sixth check today
means editing Python in two places. **Verdict: APPLY** — when the next
two anomaly checks get added (say "primary tag dropped from at-a-glance
3+ days running" and "deep dive headline reuses yesterday's headline
verbatim"), refactor to a `config/anomaly_rules.yaml` Sigma-shaped file
where each rule has `id`, `description`, `severity`, and a small Python
function reference. ~80 lines of refactor in `anomaly.py`, gates added
without code changes thereafter. Lower priority than §D.3 wins; do it
opportunistically.

#### OpenCTI / MISP — **SKIP**

Both are multi-org STIX-aware threat-intel platforms. They solve sharing
and federation; you have no peers and no sharing requirement. Their
internal data models are 5-10x richer than this pipeline needs and
their UIs are ops-grade. SKIP entirely.

#### Maltego / Palantir Gotham — link-analysis UI — **SKIP for now**

The interesting concept is the *workflow*: pivot off an entity, expand
neighbors, mark interesting nodes, save the canvas as an investigation.
Morning-Digest delivers a *rendered email* to a human reader, not an
interactive canvas. If §B.2 continuity ever gets built and the user
wants to spelunk the entity graph, a tiny PyVis or Cytoscape-JS view
over the daily graph would deliver this — but it's a feature waiting on
the substrate. SKIP today.

#### ELK / OpenSearch + Kibana, Grafana — **SKIP for the briefing, MAYBE for ops**

The briefing is conceptually a dashboard already (it has at-a-glance,
deep dives, weather, markets, calendar — same shape as a Grafana page).
Re-implementing it on top of Kibana would lose the email-render path that
is the whole point. The one place a real dashboard would help is *ops*:
`scripts/source_health.py` and the run-meta artifacts
(`stages/briefing_packet.py:118-124`) are screaming for a Grafana
panel showing per-feed health, stage timings, and coverage-gap recurrence
across weeks. **Verdict: MAYBE for ops only** — and even then, a plain
HTML page generated by a 50-line script that aggregates
`output/artifacts/*/source_health.json` and
`output/coverage_gaps_history.jsonl` is probably enough. Don't add
Prometheus/Grafana for one user.

#### DCGS / TAC / GETS — **SKIP, architectural inspiration only**

These are federated multi-INT systems built around classification,
need-to-know, sensitive-source protection, and provenance for legal
chain-of-custody. The user is one person reading their own digest. SKIP.

#### Recorded Future / Mandiant / Flashpoint output style — **APPLY**

Worth imitating: numbered key takeaways (BLUF), inline footnoted
sources, confidence-band tags (high/medium/low) next to each claim,
explicit "we did not find evidence of X" negative findings, an
**indicators-to-watch** section. Morning-Digest already partly does this
— `analyze_domain` requires "what to watch for"
(`prompts/analyze_domain_system.md` via `_SHARED_RULES`,
`stages/analyze_domain.py:455`), and deep dives are required to
"end with specific indicators to watch"
(`prompts/cross_domain_system.md:29`,
`prompts/cross_domain_execute.md:33`). Confidence bands and footnoted
inline sourcing are not yet present. See §D.3 (calibrated uncertainty)
for the concrete proposal.

### D.3 Tradecraft / methodology patterns — most of the WINs live here

#### Calibrated estimative language (Sherman Kent / ICD 203) — **WIN**

LLMs hedge softly by default ("could," "may," "potentially," "appears
to") in ways that read like calibrated uncertainty but aren't —
nothing is anchored to a probability band. The pipeline's response to
this today is a partial blocklist: `_SHARED_RULES`
(`stages/analyze_domain.py:452-454`) tells the desk model not to use
"it remains to be seen / only time will tell / the situation is fluid";
`cross_domain_system.md:9-11` repeats it; `assemble.py:52-56` regex-blocks
four hedged seam openings. That catches the worst phrases and ignores the
rest. The Kent ladder ("almost certain ≥95%, very likely 80-95%, likely
60-80%, roughly even 40-60%, unlikely 20-40%, very unlikely 5-20%, almost
no chance ≤5%") is the canonical reference (ICD 203, "Analytic
Standards"). **Verdict: WIN.** Two-stage fix:

1. **Demand a band tag where uncertainty is asserted.** Extend the
   `at_a_glance` and `deep_dives` schema with an optional
   `estimative_confidence: high|medium|low|null` field
   (`prompts/cross_domain_execute.md:43-65`,
   `prompts/cross_domain_system.md:46-58`,
   normalized in `cross_domain/parse.py:_validated_output`). Where the
   `analysis` field contains a forward-looking claim ("this likely
   forces…", "expect X within…"), the model must populate the field.
   Render it as an inline tag in the email
   (`templates/email_template.py:108`-area).
2. **Lint hedge usage at assemble time.** Add ~30 lines to
   `stages/assemble.py` that scan `facts`, `analysis`, and deep-dive
   body for the standard hedging vocabulary ("could", "may", "might",
   "possibly", "potentially", "perhaps", "suggests that") and require
   each occurrence to be co-located within ~80 chars of either an
   attribution ("X said", "according to Y") or a band tag. Items that
   fail land in `assemble_contract_issues` (already present at
   `stages/assemble.py:285-302`) and are surfaced in the digest's
   diagnostics or anomaly report. This is the *highest ROI single change
   in the appendix*: ~30 lines of post-processing, no new model calls,
   sharply better epistemic discipline. Do not let the lint fail the
   pipeline — log and surface.

The seam annotations already carry `confidence: high|medium|low`
(`prompts/seam_annotations.md:18`,
`stages/seams.py:368-370,440-447`); standardize on the same vocabulary
so renderers and downstream stages can treat all confidence the same way.

#### BLUF / tearline structure — **PARTIAL → tighten**

The briefing follows BLUF in spirit (At a Glance → Deep Dives → Coverage
Gaps → Week Ahead) but the *individual items* don't. A canonical
intel-product item leads with the key judgment, then supporting facts,
then context. `analyze_domain`'s schema is `headline → facts → analysis`
(`stages/analyze_domain.py:402-404`) — the "facts then analysis" order
is the inverse of BLUF; the analytical *judgment* arrives second. The
template surfaces this as `Sources / Analysis / Thread` voice labels
(`templates/email_template.py:108`), which is honest about the structure
but not BLUF. **Verdict: PARTIAL.** Two cheap moves:

1. Add a `bottom_line` field to the desk schema (1 sentence, the lead
   judgment) and render it bolded above `Sources` in the template. ~15
   lines across `stages/analyze_domain.py:402-411`,
   `cross_domain/parse.py`, and `templates/email_template.py:104-111`.
2. For deep dives, require the first paragraph to be the BLUF and the
   `why_it_matters` callout to be the tearline summary — the template
   already renders `why_it_matters` in a callout box
   (`templates/email_template.py:189-194`); the field exists; it just
   needs the prompt to enforce it (`prompts/cross_domain_execute.md:27-36`
   already says "what happened → why it matters → what to watch for"
   but in the *body*; require the **first sentence** of body to be the
   judgment).

This is a writing-style change with one schema field and one prompt
edit. ~20 lines. Worth doing.

#### Analysis of Competing Hypotheses (ACH) — **PARTIAL → already mostly mapped onto seams**

Heuer's ACH is the standard SAT for adjudicating among rival
explanations: list hypotheses, list evidence, score consistency, prefer
the hypothesis least disconfirmed. `seams.py`'s `causal_divergence` and
`framing_divergence` types
(`stages/seams.py:37-43`, `prompts/seam_annotations.md:23-30`) capture
the *evidence-of-disagreement* layer of ACH but not the
*scoring-against-hypotheses* layer. The output is "sources A and B
disagree about cause," not "of three candidate causal mechanisms,
mechanism 2 is least disconfirmed by available reporting." **Verdict:
PARTIAL.** Building real ACH is not worth it — Heuer's matrix only pays
off when you have ≥3 hypotheses, ≥6 evidence items, and analytical time
on the order of hours. At one user × ten minutes of reading × ~50
items/day, the existing seam framing captures what an LLM will reliably
produce. **What to do:** add an explicit `competing_hypotheses` field
to the **deep_dive** schema (1-3 short hypothesis strings, each with one
`disconfirming_evidence` excerpt). This shows up in deep dives only —
where the time budget exists — not at-a-glance items. ~25 lines across
schema, prompt, and template.

#### Structured Analytic Techniques — Key Assumptions Check, Indicators List, Devil's Advocacy — **MIXED**

- **Key Assumptions Check.** The `seam_annotations` schema explicitly
  forbids it (`prompts/seam_annotations.md:72`: "Do not use
  `embedded_premise`. Assumption tracking is out of scope."). That was
  a deliberate scope decision. Reversing it would require its own
  stage; the LLM-tradecraft fit is OK but "what does today's coverage
  *assume* that should be checked?" is a notoriously low-yield prompt
  in practice — models hallucinate trivia like "assumes the journalist
  is reporting accurately." **SKIP unless requested.**
- **Indicators List / I&W.** Each desk and deep dive already ends with
  "what to watch for" (`stages/analyze_domain.py:455`,
  `prompts/cross_domain_system.md:29`). What's missing is the **register**
  — the same indicator should accumulate across days so "watch for
  Hormuz closure" appearing on day 1, day 4, and day 9 becomes a flag
  on day 9. **Verdict: MAYBE WIN** — ~60 lines: append today's
  indicators to `output/indicators_history.jsonl`, load the last 14
  days at the start of `cross_domain.run`, surface "indicators recurring
  ≥3 times in last 14 days" as an explicit input to the planning
  prompt. Cheaper if §B.2 continuity is built; standalone if not.
- **Devil's Advocacy / Red Team.** No stage today attacks the draft.
  See dedicated entry below.

#### Devil's-advocate / red-team pass on the draft — **WIN**

This is the most under-implemented IC concept in the pipeline. `seams.py`
does adversarial review on *facts* (does coverage A disagree with
coverage B). Nothing reviews *the draft itself* — i.e., reads the
finished `cross_domain_output` and argues "here is what you got wrong."
**Verdict: WIN.** Sketch:

- New stage `stages/red_team.py`, runs after `cross_domain` and before
  `assemble` (config insertion at `config/pipeline.yaml:71-95`).
- One LLM call, ~3000 tokens budget, MiniMax M2 7 (already the
  cheap-pass model used by `enrich_articles` and `compress`,
  `config/pipeline.yaml:21-36`).
- Prompt: "Read this draft digest. For each at-a-glance item and each
  deep dive, identify the strongest argument *against* the analysis,
  the assumption most likely to be wrong, and any factual claim that
  is not anchored in the cited links. Return at most 5 critiques."
- Output: `red_team_critique` artifact with `{item_id, critique_type,
  one_line, evidence_pointer}` entries. Renders as an optional
  diagnostic section in dry-run output (mirror `coverage_gaps`'
  visibility model, `stages/coverage_gaps.py:29,79-86`,
  `templates/email_template.py:223-245`). ~150 lines stage + ~40 lines
  template + 60-line prompt file. **Highest-value new stage in this
  appendix.**

The devil's-advocate stage *uses an LLM call* and is therefore subject
to the same audit as everything else — its critiques should themselves
include a confidence band (D.3 calibrated uncertainty) and an
evidence_pointer that must resolve to a known URL or item ID. If you
don't gate it on evidence, it will hallucinate critiques.

#### Priority Intelligence Requirements (PIRs) — **WIN**

The IC concept: standing questions the product is answering against,
made explicit and shared between consumer and producer ("any movement
on Iran-Israel?", "AI-policy developments affecting compute export?",
"Russian arms-industry strain?"). Today, Morning-Digest's
selection-against-priorities is implicit in three places: the literal
strings `["war", "ai", "defense"]` at `config/pipeline.yaml:205-208,
219-222`; the prose "Aaron's primary interests: defense/space
technology, AI and national security, geopolitical shifts affecting US
posture" at `prompts/cross_domain_plan.md:24` and
`prompts/cross_domain_system.md:24`; and the keyword lists at
`cross_domain/parse.py:40-148` and `stages/anomaly.py:43-48`. Three
problems:

1. The priorities aren't a single source of truth. Editing them today
   means editing five places.
2. They are tag-shaped, not question-shaped. "war" matches anything
   tagged war; it cannot match "is Iran moving toward closing Hormuz?"
3. There's no concept of *standing* — a question that should be answered
   even if today's pull missed it. `coverage_gaps.py` is the closest
   analog; it asks the LLM "what's missing" but does not ask "given
   these specific standing questions, were any answered today?"

**Verdict: WIN.** Sketch:

- New file `config/priorities.yaml` with ~10 entries shaped as
  `{id, question, tags, recurring: bool, source_categories_required}`.
  Example: `{id: pir-iran-hormuz, question: "Movement toward Hormuz
  closure or strait disruption", tags: [war, energy], recurring:
  true, source_categories_required: [non-western, maritime]}`.
- Load at run start; pass into `cross_domain_plan` prompt as an
  explicit "STANDING QUESTIONS" block (~10 lines added to
  `cross_domain/prompt.py:35-95`).
- Surface in `coverage_gaps` prompt as "for each standing question,
  was today's pull responsive?" (~5 lines in
  `prompts/coverage_gaps.md`).
- Replace the hardcoded `primary_tags` lists in
  `config/pipeline.yaml:205-208,219-222` and
  `cross_domain/parse.py:150` with a derived set
  (`set().union(*pir.tags for pir in pirs)`) so the literal strings go
  away. ~30 lines of refactor.

This single change unifies five scattered priority encodings, makes
priorities user-editable as a config artifact, and gives `coverage_gaps`
a real spec to audit against. **Highest structural-clarity win in the
appendix.**

#### Sourcing tiers (primary / secondary / tertiary) — **PARTIAL → propagate**

`config/sources.yaml` already has 3 tiers (`primary-reporting`,
`analysis-opinion`, `institutional-analysis`,
`config/sources.yaml:45,77,254`). The desk prompt prose distinguishes
"primary-reporting sources" from "analysis/opinion sources" in detailed
guidance for `geopolitics_events`
(`stages/analyze_domain.py:80-94`). But the field stops there:
`stages/seams.py:173-174` and `stages/analyze_domain.py:514-515`
display it inline; `cross_domain` never sees it; `assemble.py` never
sees it; the rendered email never tags it. **Verdict: PARTIAL.**
Three small changes:

1. Propagate `reliability` from `raw_sources.rss[*]` through
   `analyze_domain.items[*].links[*]` to
   `cross_domain_output.at_a_glance[*].links[*]` (~15 lines across
   `cross_domain/parse.py:599-629` and the URL-known filter).
2. In `assemble.py`, when rendering inline source links
   (`templates/email_template.py:113-117,196-201`), emit a small badge
   for `primary-reporting` vs. `analysis-opinion` so the reader can
   see at a glance that "the WSJ says" carries different weight than
   "Tooze says." ~10 lines CSS, ~5 lines template.
3. The IC tertiary tier ("analysis of analysis") is not currently
   marked. Most analysis-opinion feeds are *secondary*; a few
   (`Proximities`, `Tooze`, `Drezner`, certain Substack threads) are
   `tertiary` because they meta-comment on other analysts. Adding a
   third tier is one config edit and one display label. ~10 lines.

This is a 40-line propagation, not a new system. The infrastructure is
already there.

#### Indications & Warning (I&W) register — **MAYBE**

Per the SAT entry above, the watch-list pattern is half-present in
"what to watch for" lines but lacks accumulation. Build only if §B.2
continuity gets built; otherwise, the standalone "indicators history
JSONL" is fine but adds little before there's a way to show
"recurring indicator X has been on the watch list for 9 days running."

### D.4 Top 3 by value-per-effort

Ranked. Each is sketched concretely so the work is unambiguous.

1. **Calibrated estimative language as a lint + schema field
   (D.3, ~50 lines).** Add an `estimative_confidence:
   high|medium|low|null` field to `cross_domain_output.at_a_glance[*]`
   and `deep_dives[*]` schemas. Edit
   `prompts/cross_domain_execute.md:42-65` and
   `prompts/cross_domain_system.md:46-58` to require the field where
   the `analysis` makes a forward-looking claim. Add a 30-line lint in
   `stages/assemble.py` (sibling to `_HEDGED_SEAM_RE` at line 52-56)
   that scans `facts`/`analysis`/deep-dive body for unanchored
   hedging vocabulary and writes findings to
   `assemble_contract_issues`. Render the band as a small badge in
   `templates/email_template.py:108-area`. **Highest ROI in the
   appendix; do this first.**

2. **PIRs as `config/priorities.yaml` (D.3, ~80 lines including
   refactor).** Create `config/priorities.yaml` with 8-12 entries
   shaped as `{id, question, tags, recurring, source_categories_required}`.
   Load at run start (`pipeline.py`), pass into `cross_domain_plan`
   prompt as a STANDING QUESTIONS block
   (`cross_domain/prompt.py:35-95`), pass into `coverage_gaps`
   prompt (`prompts/coverage_gaps.md`), derive
   `primary_tags`/`primary_domains` from
   `set().union(*pir.tags)` in
   `config/pipeline.yaml:205-208,219-222` and
   `cross_domain/parse.py:150` so the literal strings go away. **Single
   biggest structural-clarity improvement available.** Doubles as
   documentation of what the digest is *for*.

3. **Devil's-advocate / red-team stage (D.3, ~250 lines new).** New
   `stages/red_team.py` between `cross_domain` and `assemble`
   (`config/pipeline.yaml:71-95`). One MiniMax M2 7 LLM call (matches
   the cheap-pass tier at `config/pipeline.yaml:21-36`). New prompt
   `prompts/red_team.md`. Critiques rendered as an optional
   diagnostic section (mirror coverage_gaps' visibility model in
   `stages/coverage_gaps.py:29,79-86` and
   `templates/email_template.py:223-245`). Each critique itself
   carries a confidence band and an evidence_pointer to a known
   item_id or URL — no unanchored critiques. **Largest editorial-quality
   delta of the three; also the most code.**

After those, the next tier is sourcing-tier propagation (D.3, ~40
lines), then BLUF `bottom_line` field (D.3, ~20 lines), then I&W
register (D.3, ~60 lines, gated on §B.2). Sigma-style anomaly rules
(D.2, ~80 lines) and NiFi-style provenance audit (D.2, ~50 lines) are
the architectural hygiene tier; do them when adding the next anomaly
check or after the first time a deep-dive body cites something not in
the links list.

### D.5 What deliberately not to import

Concrete list, so the trap-doors are named:

- **Classification markings (CUI / FOUO / TS//SCI / ORCON / NOFORN /
  releasability tearlines).** No multi-reader audience, no clearance
  ladder, no need to redact based on a recipient's accesses. Importing
  this for "completeness" adds metadata fields nothing reads.
- **Multi-INT taxonomies (HUMINT / SIGINT / GEOINT / OSINT / MASINT /
  IMINT).** Morning-Digest is single-INT (OSINT). Tagging every item
  "OSINT" is noise. STIX kill-chain phases fall in the same bucket —
  there is no kill chain here.
- **MITRE-style giant ontologies (ATT&CK, CAPEC, CWE).** They earn
  their keep at threat-intel-platform scale (thousands of analysts,
  millions of indicators). At this scale, a 20-entry edge-type
  vocabulary outperforms a 200-entry MITRE schema for readability and
  authoring cost.
- **STIX/TAXII wire formats and OpenCTI/MISP servers.** Sharing-format
  primitives for organizations that don't share. SKIP.
- **SCIF-grade audit trails / WORM logs / HSM-backed signing.** The
  artifacts in `output/artifacts/YYYY-MM-DD/` are sufficient run-history
  for one user; cryptographic chain-of-custody adds ops weight that
  protects against threats Morning-Digest does not face.
- **Tasking workflows / collection management / RFI tickets.** Single
  user; the "tasking" is the cron schedule.
- **Storm / Kafka / RabbitMQ / Mesos orchestration.** Already covered
  in §6 against LemonGrenade's NSA stack — same conclusion holds for
  Metron, NiFi-cluster, and DCGS-style federations. A ten-stage Python
  pipeline running once a day does not need an event bus.
- **Structured Threat Information eXpression confidence scales (none /
  low / med / high / admiralty A1-F6).** Three levels (high/medium/low)
  are sufficient and match what `seam_annotations` already uses
  (`prompts/seam_annotations.md:18`). Admiralty's two-axis source-times-info
  is the kind of precision that survives only at industrial scale.
- **Heuer's full ACH matrix.** As argued in §D.3, the matrix pays off at
  scales Morning-Digest doesn't operate at. The ACH-shaped tradecraft
  worth keeping is the "competing hypotheses" *field* on deep dives,
  not the matrix scoring.
- **A separate "tradecraft training" prompt loaded into every model
  call.** Tempting and wrong — it bloats every call's system prompt
  for a benefit better delivered as small per-stage rules. The current
  per-prompt `_SHARED_RULES` pattern (`stages/analyze_domain.py:448-490`)
  is the right granularity.

The rule of thumb: import IC tradecraft *concepts* (band-tagging,
BLUF, sourcing tiers, devil's advocate, PIRs) where they map onto
concrete ~10-100 line edits to existing stages. Refuse IC *systems*
(NiFi, OpenCTI, STIX servers, multi-INT taxonomies, classification
machinery) — they assume a scale and a threat model Morning-Digest
does not have. The earned-its-keep pattern, again: small disciplines
on top of the existing pipeline; not a new platform underneath.
