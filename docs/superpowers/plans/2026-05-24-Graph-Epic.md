# Epic: Graph-Shaped Substrate and Seams Reconstruction

## Diagnosis

The Morning Briefing pipeline has accumulated three classes of structural debt that compound to produce the user-visible symptoms: an architecture that feels patched, post-run cleanup that feels mushy, and cross-desk reasoning that misses obvious connections.

The first class is **deterministic-override sprawl**. The pipeline asks the LLM to do work that Python should do — counting (`source_depth`), joining (`tag_label` re-derivation), copying (verbatim `facts`/`analysis`), classifying against a fixed vocabulary (`tag` normalization), and enforcing quotas (per-outlet caps in multiple locations) — then patches the LLM's failures with deterministic code. Each patch is real evidence that the LLM was asked to do work it can't reliably do at scale. Five separate override patterns live in `cross_domain/parse.py` alone; `_rebalance_categories` in `analyze_domain.py` manufactures fallback items when desks come up empty.

The second class is **graph-shaped reasoning expressed as a one-shot LLM prompt**. The `connection_hooks` field — structured `{entity, region, theme, policy}` tuples produced by every desk — is the most structural piece of cross-domain metadata in the pipeline, and almost nothing consumes it. Instead, `cross_domain` formats all seven desk outputs into one 26k-token user message and asks the LLM to find connections in its head. When it misses obvious cross-desk links, the failure mode is invisible because there's no candidate generation to audit. The graph-shaped data is decorative.

The third class is **seams scoped too narrowly for its stated purpose**. The current seams implementation detects framing, selection, causal, and magnitude divergence between sources — useful work, but a thin slice of what seams ought to do. The underlying intent is to surface what daily news structurally strips away: contextual grounding the reporting omits, calibrated middle positions when coverage is pulled toward rhetorical extremes, cross-desk interconnections that get reported as siloed events, and recognition of shallow consensus where headline agreement hides detail-level disagreement. The current taxonomy covers one quadrant of that vision.

These three classes of debt have a common root: the Python/LLM boundary is drawn in the wrong place. The fix isn't more sophisticated machinery; it's redrawing the boundary correctly and dropping work that doesn't earn its place.

## Vision and operating principles

The redesigned pipeline applies a single principle systematically: **LLMs do judgment and generation; Python does counting, joins, structural transforms, and quota enforcement; embeddings do semantic similarity. Every override pattern in the current pipeline is the LLM being asked to do Python work.**

From this principle, four operating rules follow.

First, **wherever the prompt asks the LLM to do something the code then overrides, remove the prompt instruction**. If Python can derive the value, drop the schema field and derive it. If the LLM should reliably produce it, tighten the prompt and remove the override. Either direction eliminates the "LLM does it, code corrects it" pattern.

Second, **manufactured content where evidence doesn't support it is forbidden**. This applies as a voice constraint (don't fabricate analytical connections) and as a structural rule (don't synthesize fallback items to compensate when source material is empty; the honest output is silence).

Third, **stages that don't drive pipeline behavior or trigger human action get dropped, regardless of whether they sound valuable**. Diagnostic-only stages whose output is consumed by neither code nor humans are decoration. The smoke-detector view (consolidated anomaly + source_health + enrichment provenance) is the exception: it's pipeline self-check, and reading it informs operational decisions.

Fourth, **`audience.yaml` is the single source of truth for personalization**. Topical interests, source attitudes, voice posture, and location all live there. Hardcoded priority strings across five files are an anti-pattern. Note that a draft of this new file already exists but is not yet used. 

Fifth, **use the cheapest schema-reliable model through the build; defer all model selection to one bakeoff after Phase 4**. During Phases 1–3, run the schema-heavy stages (`analyze_domain`, `cross_domain`, `seams`) on the cheapest model that reliably produces valid structured JSON — currently **MiniMax M2.7** ($0.30 in / $1.20 out per 1M), which the pipeline already trusts for lighter stages and which this plan elsewhere names as the JSON-reliability floor. Today those stages run on Kimi K2.6 (~3.3× the output cost) for no reason that survives the refactor; testing is the high-iteration window where that cost matters most, and there's a real chance MiniMax M2.7 already meets "minimum viable" so no structured-stage bakeoff is ever needed. Do **not** commit per-stage models inside refactor PRs (PR-G's Kimi K2.6 and PR-H's bakeoff are pulled out — see those PRs). Two reasons this is more than re-pricing: (1) the epic *shrinks* what each LLM must emit — dropping `tag`/`tag_label`/`source_depth`/verbatim copies (PR-A) and collapsing cross_domain to item_id-selection plus one-liners (PR-D) — which raises the floor of which cheap models can comply, so even gpt-oss-120b/-20b (rejected *today* for malformed JSON) deserve a re-test against the *reduced* schema; (2) `contextual grounding` (PR-H) is the one stage where model training-knowledge genuinely affects quality, so it keeps a narrow bakeoff. Both bakeoffs run once, after Phase 4, against real reconstructed output — never folded into refactor work.

The result is a pipeline where the LLM is asked to do the smallest possible piece of judgment or generation work, surrounded by Python that handles structure, counting, and enforcement. Cross-desk reasoning is precomputed by inverted-index queries before the LLM sees candidates. Article-level wire-syndication is collapsed by clustering before desk synthesis. Seams expands from a single divergence-detection LLM call into a structured set of components with different evidence models for each kind of editorial signal.

## Success criteria

Two observable criteria, both verifiable from the post-epic codebase:

**Zero deterministic overrides anywhere in the pipeline.** No Python code modifies LLM output to correct behavior the prompt should have produced. This criterion applies to every stage, not just `cross_domain/parse.py`.

The operational test that makes this verifiable: *Python may **derive** a value the LLM shouldn't have been asked for, **drop/truncate/reorder** items, and **validate** schema; Python may **not rewrite the semantic content of a field the LLM emitted**.* Under that test, `_recompute_source_depth` (derive from links) and per-outlet caps (drop) are legitimate; `_normalize_tag`'s 100-entry keyword remap (rewrite) is the override class being eliminated. Where the cheaper fix is to stop asking the LLM for the value at all, the schema field is dropped rather than the override relaxed.

The master removal checklist is the LLM-vs-deterministic audit in the source assessment (`docs/exploration/lemongraph-seams-assessment.md`, Appendix A — 15 findings, 8 HIGH / 6 MEDIUM / 1 LOW). Completion means every enumerated finding is either removed or explicitly moved to the "not doing on purpose" bucket with a one-line reason. PR-A is the primary vehicle; the regex sweep there is expected to surface a few more `_normalize_*` / `_validate_*` instances not in the original 15 — those get appended to the same checklist as found.

**`config/audience.yaml` is the single edit point for personalization.** Changing the digest's priorities, voice, source attitudes, or location requires editing exactly one file. Today it requires editing five.

These criteria are the floor, not the ceiling. Editorial-quality improvements (calibrated estimative language, BLUF restructuring, sourcing-tier badges) are queued for later epics; they aren't necessary to declare this one complete.

## Regression and verification approach

The pipeline is **not running at all** right now — no daily delivery, by choice — which relaxes the regression bar substantially: we are not preserving daily production output through the refactor. The bar for each PR is "does the new code produce reasonable output when reviewed," not "does it diff-match the prior implementation."

Because nothing is delivered daily, the only data available through Phases 1–4 is **test-data runs** — manually-triggered runs over saved or fresh source pulls, inspected by hand. There is no week-of-production window to measure against. It does not make sense to resume day-to-day delivery until Phase 4 (seams reconstructed) or Phase 5 (smoke detector in place); the structural-cleanup and substrate phases are validated by inspecting a handful of test runs, not by living on the output. Phases 1–3 ship under spot-check verification of test runs. Phase 4 reconstructs seams in ways that *intend* to differ from current output, so verification is editorial: a batch of inspected test runs with the question "do these annotations feel useful."

**Conditional-PR gates are decided by reasoning, not by production counts.** Several PRs were originally gated on metrics like "≥5 false-negatives per week" — meaningless when there is no weekly production stream. Replace those gates with: enumerate the most likely failure modes for the question each stage asks, inspect a small set of test runs for whether those modes actually appear, make a reasonable keep-or-drop call, and push the residual long-tail into the "not doing on purpose" bucket with a one-line reason. A few inspected runs plus known failure-mode reasoning is the evidence standard, not a production time-series.

**Feature-flag every new-vs-old behavior path.** The cross_domain rewrite (PR-D), article clustering (PR-E), the embedding capability (Phase 3), and seams reconstruction (Phase 4) each ship behind a config flag that toggles the new path against the preserved prior implementation. Default to the new path, but keep the old path runnable for side-by-side test-run comparison and as a one-line rollback when daily delivery eventually resumes — no revert-and-redeploy needed. Flags for a path get removed once that path has been validated across enough test runs and the old code is deleted.

## Phase breakdown

**Phase 1: Structural cleanup.** Three working PRs plus several dead-code removals, all independent of graph work and shippable in any order.

PR-0 instrumentation: a domain_research loop tracking instrumentation (a usage counter logged per run) and other relevant tracking metrics, so we have data before Phase 5's keep-or-drop decision. Ideally, the tracked metrics will be useful for any other downstream decisions or understanding of what is happening in the pipeline. 

PR-A handles the Appendix A audit findings: drop `tag_label` from cross_domain schema and derive in code; derive `tag` from desk-of-origin rather than asking the LLM and re-mapping via `_TAG_KEYWORDS`; switch cross_domain plan to emit a *selection* of item_ids rather than verbatim-copying facts/analysis; relax "exactly N" quotas to "up to N"; drop prompt-side caps that duplicate code-side caps. Also includes the regex sweep — drop `_HEDGED_SEAM_RE` in favor of prompt discipline, audit any other `_normalize_*` / `_validate_*` patterns for the same anti-pattern.

PR-B creates `audience.yaml` and threads it into the prompts that need it. The legacy `primary_tags` / `primary_domain_tags` / `tertiary_tags` lists derive from interest entries at load time. The voice posture (with its embedded causal-tracing instruction replacing the considered-and-rejected framework library), the source attitudes (with the consensus-handling guidance pointing at seams as the consensus-robustness check), and the location all live in this file.

PR-B is the highest-blast-radius change in Phase 1 — it threads config into prompt templates across multiple files, where a silently-dropped interest or attitude reads as normal output and a spot-check won't catch it. So its verification is stronger than the other Phase 1 PRs: **snapshot the fully-rendered prompts before and after the refactor and diff them.** When `audience.yaml` is populated with today's hardcoded values, the rendered prompt text should be substantially identical to the pre-refactor prompts; any unexpected delta is a threading bug. This makes PR-B's correctness mechanically checkable rather than editorial.

PR-C consolidates per-outlet cap enforcement to one location (assemble), deleting the duplicate implementations in `cross_domain/parse.py` and `analyze_domain.py`. Reliability-tier propagation rides along: extend the `reliability` field flow from `raw_sources.rss` through `domain_analysis.items.links` to `cross_domain_output.at_a_glance.links` so the assemble stage can render source-tier badges. Data is already in `sources.yaml`; this is propagation only.

Dead-code removals in Phase 1, executed as part of the relevant PR or as small cleanup PRs: `_rebalance_categories` (manufactured fallback items), the Phase 1 fallback path in `assemble.py:317-346` (legacy compatibility for a missing `cross_domain_output` that won't occur), `briefing_packet` (the chat-context export that's not consumed), `coverage_gaps` (content-diagnostic with no actionable consumer), and the planned-but-never-built `audit_provenance` work (its anchoring-check requirement gets carried forward as a design constraint for the future Editor stage).

**Phase 2: Substrate.** Three PRs that build the foundation for cross-desk reasoning.

PR-D promotes `connection_hooks` to inverted indexes — `{entity → [item_ids]}`, `{theme → [item_ids]}`, `{policy → [item_ids]}`, `{region → [item_ids]}`, `{outlet → [item_ids]}` — built once after `analyze_domain` completes. Cross_domain's prompt input shrinks from the full 7-desk dump to a precomputed candidate list of pairs sharing ≥2 hooks across ≥2 desks. The LLM writes the one-line `cross_domain_note` for each surviving candidate. `_ensure_primary_glance_coverage` becomes unnecessary because the index can guarantee primary-tag coverage deterministically. Includes a note for post-PR-D evaluation: the two-turn plan/execute pattern may collapse to one turn once candidates are pre-filtered, but a loop has conceptual value when there's enough work to justify the overhead — keep if the planning step does real selection work after candidates arrive pre-filtered, drop if it doesn't. Note: look at the data produced during a run and see if caps also need to be added. 

PR-E adds a `cluster_articles` pre-pass between collect and enrich_articles. Title-shingle Jaccard single-link clustering at a starting threshold around 0.55. Each RSS item gets a `cluster_id`; `analyze_domain`'s "merge into ONE item" rule sees the cluster_id and acts deterministically; `_recompute_source_depth` counts distinct clusters rather than distinct domains, eliminating the Reuters-syndicated-via-AP false-corroboration class. Diagnostic `cluster_log.json` artifact for false-negative auditing.

PR-D and PR-E are **not** hard-ordered; the only real coupling is that both rewrite `_recompute_source_depth` (PR-D from the index's distinct domains, PR-E to distinct clusters), and we don't want to refactor that function twice. The clean resolution: settle `source_depth` on its **final** form — count of distinct clusters — once, and have whichever of the two lands second consume cluster-aware items rather than re-touching the counter. The source assessment argues clustering is the natural foundation (§B.1, §B.8: "build §B.1 first... then the adapters on top"), so doing PR-E first, or at least defining `source_depth` in cluster terms up front, avoids the rework. Per-PR docs settle the exact order; the hard "PR-E depends on PR-D" constraint is dropped.

**Phase 3: Embedding capability.** One PR, two call sites. PR-E and PR-D both rely on lexical matching (title-shingle Jaccard for clustering; exact-string keys for the inverted index), and both have the same failure mode: semantically-equivalent things that don't share enough surface tokens (`"Houthi missile strike"` ≈ `"Yemen attacks shipping"`; `"Sam Altman"` vs `"OpenAI"`). This PR introduces a single Fireworks `/v1/embeddings` capability and wires it to both: (a) union the clustering edge set — `(jaccard ≥ T_lexical) OR (cosine ≥ T_semantic)`; (b) a hook-normalization pass that merges inverted-index keys at cosine ≥ ~0.85. One embedding call, one threshold-tuning exercise, both sites served. Default embedding model: Nomic-embed-text-v1.5; switch to BGE-large only if recall remains insufficient.

This PR is gated by reasoning, not by a production count (there is no daily stream — see the verification section). Decide from inspected test runs: do real wire-story pairs slip past lexical clustering, and do obviously-equivalent entity strings sit as separate index keys, *in the runs we actually have*? If the most-likely failure modes show up in a handful of test runs, build it; if they don't, the long-tail goes to the "not doing on purpose" bucket. The capability can also ship for one site and not the other if only one shows the failure.

**Phase 4: Seams reconstruction.** Three PRs rebuilding seams around the components the underlying vision requires. Each Phase 4 PR's plan doc should note what cross-day-persistable state it produces, so the future continuity epic starts with a list instead of a search.

PR-G handles extremity detection and calibrated-middle synthesis. Using PR-E's event clusters, identify clusters with multi-outlet coverage and ask the LLM to characterize where rhetorical extremes sit within the cluster, then articulate the calibrated middle position. (Build and test this on the cheap schema-reliable model per the fifth operating rule; the final model choice is deferred to the post-Phase-4 bakeoff, not committed here.) The prompt explicitly allows "this looks bimodal but one side is right" as an output — calibration toward the middle as a default is its own bias and must not be the LLM's only available conclusion.

PR-H handles contextual grounding — surfacing the historical and structural backdrop daily reporting strips away. This is the only stage where model selection genuinely affects output quality, because the LLM is bringing training-knowledge background that isn't in the source pull, so this is the stage that justifies a bakeoff at all. Build the stage on the cheap default; defer the bakeoff to the single post-Phase-4 model exercise (candidates worth including: DeepSeek-V4-Pro — Fireworks premium, 1M context, ~60% the cost of Anthropic Sonnet — plus at least one mid-tier Fireworks model, judged on grounding quality against real reconstructed output). Evidence model differs from the divergence gate: context claims must be falsifiable and signaled with confidence rather than anchored to ≥2 sources.

PR-I refactors current divergence detection (framing, selection, causal, magnitude) onto the new substrate, expressing the evidence gate as a graph-query shape using the inverted index, and folds in the shallow-consensus join — when `source_depth: widely-reported` coincides with a seam annotation on the same `item_id`, mark the consensus as shallow and render a badge. The 2×2 of source-depth × seam-presence becomes a structured signal rather than a decoration.

Cross-desk interconnection from the original seams vision is *not* a separate Phase 4 PR — it's PR-D's inverted index work, because the index is the mechanism. The connection narratives live in `cross_domain_output`, not in `seam_annotations`.

**Phase 5: Anomaly and smoke detector.** Consolidate the diagnostic surface and add the committed news-failure-mode checks.

Anomaly stage absorbs source_health (currently a separate script with a 14-day window writing `source_health.json`) and enrichment provenance (per-item enrichment tier, success/failure rates from the enrich_articles stage). The unified smoke detector renders in dry-run output by default, with a high bar for daily-email visibility — the detector is pipeline self-check, not reader-facing content.

New checks: galaxy-brained over-coverage (flag when source_depth is concentrated in a short time window, suggesting attention-economy distortion rather than genuine importance), genre confusion (finer per-article reliability tiering that distinguishes op-eds inside primary-reporting outlets from straight reporting), local fallback in `prepare_local.py` (try Cache Valley first, fall back to Utah-wide, fall back to Mountain West if both are dry; 3-day grace period before the anomaly check fires on missing local), Sigma-rules refactor (refactor anomaly into `config/anomaly_rules.yaml` *only* if adding the next two checks brings the total to five — three current plus two new — otherwise defer the framework refactor).

Domain_research loop decision lives here, informed by Phase 1's tracking data: keep if the loop fires routinely and produces value; simplify if it fires but adds little; drop if it rarely fires at all.

## What we are not doing, and why

This section is deliberately standalone so future-self and any other reader can see what was considered and rejected.

**Full graph framework (`Node` / `Edge` / `DigestGraph` / `Adapter` classes).** The lightweight inverted index in PR-D captures the practical benefit without committing to a graph framework. The framework only earns its keep if there are four-plus adapters all querying the same intermediate state. We aren't there. Revisit only if PR-D plus hook normalization plus the inverted-index extensions in Phase 4 start feeling ad-hoc.

**LemonGraph and LemonGrenade as dependencies.** NSA-era infrastructure (Storm, RabbitMQ, MongoDB, Zookeeper, supervisord, JVM). Categorically wrong scale for a single-user daily pipeline. The pattern is good; the implementation is wildly out of scope. The assessment that recommended these dependencies was explicit that the *pattern* should be stolen and the *implementation* avoided.

**PIRs as IC tradecraft concept.** The structural problem (priorities hardcoded in five files) is real and solved by `audience.yaml`. The IC framing (the digest as a contract to answer standing questions) is solving a problem we don't have. The digest is "help me stay informed," not "answer these specific questions every day or you've failed."

**Editor stage in this epic.** The Editor stage's value depends on having a clean draft to attack. Phases 1-4 produce that clean draft. Editor against the current mushy output would spend its budget on the same items the existing patches already fix. Editor moves to a follow-on epic alongside continuity. The anchoring-check requirement from the dropped audit_provenance work is the design constraint that carries forward.

**Cross-day continuity in this epic.** Significant design effort with no confirmed editorial use case beyond stale-framing detection. The final graph design from Phases 2-4 will inform what cross-day state is worth persisting; we don't know yet what the persisted shape should look like, and building it speculatively wastes work. Revisit after Phase 4.

**Actionable coverage_gaps (Crawl4AI search to fill missing topics).** Adaptive-pipeline architecture shift, with feedback loops, termination conditions, and a budget. Significant work for an unproven win. Since the diagnostic-only version wasn't driving curation behavior either, we're dropping coverage_gaps entirely rather than upgrading it.

**Analytical-framework library in `audience.yaml`.** A named-framework selector for deep dives (three-lens / four-lens / open) was considered and rejected. The LLM picking among frameworks adds uncalibrated work for uncertain gain, and the substance of both frameworks fits cleanly in the voice posture as a causal-tracing instruction without requiring framework selection. If a week of deep-dive output suggests the LLM is missing the causal-tracing posture, revisit; otherwise, the simpler version is the right floor.

**STIX/MITRE/multi-INT taxonomies.** Hundreds of edge types where twenty suffice. Wrong tradeoff for one user. The IC concepts worth importing are tradecraft (calibrated language, BLUF, sourcing tiers, devil's advocate); the IC systems aren't.

**Storm/RabbitMQ/Mesos/Kafka orchestration.** Operational complexity for a five-minute single-machine job. `ThreadPoolExecutor` handles desk-parallel work; nothing more is needed.

**Classification markings (CUI/FOUO/SCI/NOFORN/ORCON).** No multi-reader audience to redact for.

**Calibrated estimative language as schema field; BLUF restructuring; sourcing-tier badges as full inline rendering.** Real editorial-quality improvements identified in Appendix D.3, but they solve a different problem than the structural mushiness this epic addresses. Queued for a future editorial-improvements epic. The reliability-tier propagation in PR-C is the *only* piece of D.3 we're pulling forward, because the data is already in `sources.yaml` and not propagating is a defect rather than an enhancement.

**gpt-oss model substitution.** Smaller models produce malformed structured JSON more often than MiniMax M2.7 *under today's schema*. Cost savings disappear into parse failures and retries. But this epic deliberately *shrinks* the schema each stage must emit (PR-A drops `tag`/`tag_label`/`source_depth`/verbatim copies; PR-D collapses cross_domain to item_id-selection plus one-liners), which raises the floor of which cheap models can comply — so the rejection must be re-litigated against the *new* schema, not carried forward. The re-test belongs in the post-Phase-4 model exercise as a parse-rate benchmark on a single stage with the reduced schema (gpt-oss-120b at $0.15/$0.60 and -20b at $0.07/$0.30 are the cheapest candidates) — not folded into refactor work.

**Sigma-rules refactor for anomaly without ≥2 new rules.** The pattern earns its keep when there are enough checks to justify the framework. Three current checks plus two new (galaxy-brained, genre-confusion) is the threshold; if Phase 5 doesn't actually add both, defer the refactor and ship the new checks as imperative Python alongside the existing ones.

**Two-turn cross_domain pass collapse in Phase 2.** May become unnecessary after PR-D pre-filters candidates, but the decision is a post-PR-D experiment, not a Phase 2 commitment. A loop has conceptual value when there's enough work to justify the overhead; evaluate after seeing the new shape, and remove only if the planning turn isn't doing real selection work.

## Per-PR documents

Each PR has its own plan document at `docs/plans/pr-NN-name.md` written when the PR is opened, not all upfront. Each captures: the PR's goal (one paragraph), the file-level changes, decisions made and rejected, open questions specific to this PR, the PR-level success criterion, and the verification approach. Writing them per-PR rather than all at once lets later PRs benefit from what we learned in earlier ones — and keeps each plan small enough to comfortably fit in context for the work it describes.

The epic itself stays roughly stable across the project. It gets updated when phase boundaries reshape but mostly stays as the strategic record of where this work started and why.
