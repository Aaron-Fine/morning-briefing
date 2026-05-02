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
