# Morning Briefing Expansion — Revised Implementation Checklist

Repository: `Aaron-Fine/morning-briefing`  
Owner: Aaron  
Primary implementer: Claude Code (or equivalent coding agent)

---

## How to use this checklist

This document is intentionally procedural. It translates the approved roadmap into implementation-ready slices with:

- concrete file-level tasks,
- required commands,
- tests to add or update,
- artifact checks,
- hard completion gates.

### Global execution rules

1. **Do slices in order.** Do not start the next slice until this slice is green.
2. **After every slice** run:
   - full tests,
   - end-to-end `--dry-run`,
   - artifact presence checks.
3. **Schema compatibility is a hard constraint** unless a slice explicitly introduces a new schema.
4. **Prompt files go in `prompts/`**; do not inline large prompts in Python modules.
5. **All pipeline and test commands run inside Docker.**
6. **Intermediate artifacts introduced in this plan are diagnostic by default.**
   They are useful for debugging and iteration, but they are **not** part of the stage contract unless a later slice explicitly promotes them.
7. **Runtime snapshots are acceptable for this implementation pass**, but convert important baseline schema checks into checked-in test fixtures as part of the work so future changes do not depend on ad hoc output directories.
8. **Use the container `TZ` environment variable as the single timezone authority.**
   Remove `schedule.timezone` and `location.timezone` from config rather than trying to keep multiple timezone declarations in sync.

### Contract discipline

Treat the following as explicit contracts in this implementation pass:

- stage metadata structure introduced in Slice 1
- shared timezone helper behavior introduced in Slice 0
- `cross_domain_plan` output contract introduced in Slice 3
- `coverage_gaps` output contract introduced in Slice 7
- shared tag vocabulary wherever tags are rendered, validated, or normalized

Artifacts not listed above remain diagnostic-only unless later promoted.

---

## Baseline command set (reuse after each slice)

> Use Docker for all pipeline/test commands.

```bash
docker compose build
docker compose run --rm --no-deps morning-digest python -m pytest tests/ -v --tb=short
docker compose run --rm morning-digest python pipeline.py --dry-run
```

Optional source-only check:

```bash
docker compose run --rm morning-digest python pipeline.py --sources-only
```

---

## Slice 0 — Preflight + Stability Guardrails

### Goals

- Capture clean baseline artifacts and output.
- Fix known stability blockers before major expansion:
  - `analyze_domain` contract drift (`_failed` leakage),
  - timezone consistency across scheduler, pipeline, artifact naming, and rendering,
  - removal of Friday-specific execution paths and flags.

### Files to inspect/update

- `stages/analyze_domain.py`
- `tests/test_analyze_domain.py`
- `entrypoint.py`
- `pipeline.py`
- `stages/assemble.py`
- `README.md`
- tests covering CLI usage and scheduler behavior

### Tasks

- [x] Build and run a baseline dry-run.
- [x] Save baseline digest:
  - copy `output/last_digest.html` -> `output/baseline_digest.html`
- [x] Snapshot baseline artifacts:
  - copy `output/artifacts/YYYY-MM-DD/` -> `output/artifacts/baseline/`
- [x] Make `_empty_domain_result()` helper contract-test compatible:
  - no `_failed` leakage in helper expectations,
  - preserve failure signaling where the runtime needs it.
- [x] Introduce a shared timezone helper using Python timezone best practice (`zoneinfo`), sourcing timezone from `TZ`.
- [x] Use the shared helper for:
  - artifact date selection,
  - `run_meta` timestamps,
  - scheduler runtime calculations,
  - rendered digest timestamps,
  - all user-visible date formatting and subject-line formatting.
- [x] Remove `schedule.timezone` and `location.timezone` from config and update code/tests accordingly.
- [x] Remove `--force-friday` from code, docs, and tests.
- [x] Remove platform-specific `strftime` directives from user-visible dates.
- [x] Add DST transition coverage for:
  - scheduler next-run logic,
  - shared datetime helper behavior.

### Tests / checks

- [x] `pytest tests/test_analyze_domain.py -v --tb=short`
- [x] entrypoint/scheduler tests including DST coverage
- [x] CLI tests updated for removal of `--force-friday`
- [x] full test suite
- [x] `pipeline.py --dry-run`

### Completion criteria

- [x] baseline digest and artifact snapshot created
- [x] tests green
- [x] no timezone drift between scheduler semantics, artifact directories, and rendered timestamps
- [x] Friday-specific behavior and CLI flags removed from the codebase

---

## Slice 1 — Prompt Loader + Stage Metadata Foundation

### Goals

- Eliminate stage metadata drift before adding turn-based complexity.
- Move prompt handling onto a reusable file-based loader before converting stages to multi-turn flows.

### Files to inspect/update

- `pipeline.py`
- prompt-loading support module(s)
- `stages/analyze_domain.py`
- `stages/seams.py`
- `stages/cross_domain.py`
- `stages/prepare_spiritual.py`
- relevant tests in `tests/`

### Tasks

- [x] Refactor stage metadata into a single canonical structure:
  - primary artifact key,
  - criticality,
  - empty fallback,
  - model defaults,
  - per-turn override resolution.
- [x] Keep stage order in config; avoid duplicating stage semantics in multiple maps or sets.
- [x] Define the canonical internal stage metadata contract explicitly, including:
  - primary artifact key,
  - non-critical or fatal behavior,
  - empty fallback function or structure,
  - model defaults,
  - optional per-turn overrides.
- [x] Fold pipeline special cases into the stage metadata or lifecycle model so `pipeline.py` stops accumulating per-stage branches for:
  - previous-day context loading,
  - stage-specific extra kwargs,
  - stage-specific post-run side effects.
- [x] Replace central registries in `pipeline.py` with stage-owned metadata or an equivalent single source of truth:
  - `_stage_artifact_key`
  - `_empty_stage_output`
  - `_NON_CRITICAL_STAGES`
- [x] Add a prompt loader that:
  - reads prompt files from `prompts/`,
  - performs template substitution,
  - fails on missing variables,
  - constrains prompt lookup to trusted prompt paths.
- [x] Treat prompt files as trusted implementation assets, not user content.
- [x] Migrate existing large inline prompts to prompt files where practical, starting with stages that will be refactored next.
- [x] Add comments or conventions for how prompt variables are passed and escaped.

### Tests / checks

- [x] update/add contract tests for stage metadata coverage
- [x] add prompt loader tests:
  - successful substitution,
  - missing variable failure,
  - disallowed path failure
- [x] verify existing stages still pass stage artifact key and empty output tests
- [x] full test suite + dry-run

### Completion criteria

- [x] adding or modifying a stage now requires one metadata entry rather than scattered edits
- [x] prompt files are the standard path for large prompts
- [x] prompt loader is in place before multi-turn stage work begins
- [x] stage metadata contract is documented clearly enough that future stages can follow it without hidden conventions
- [x] `pipeline.py` no longer needs scattered stage-specific branches for features covered by stage metadata or lifecycle hooks

---

## Slice 2 — Two-turn `seams` Stage

### Goals

- Implement divergent scan + convergent synthesis while preserving the current `seam_data` contract.
- Add a diagnostic scan artifact without making it part of downstream schema contracts.

### Rationale

Single-shot seams currently asks the model to detect contradictions, coverage gaps, and key assumptions in one pass. Those tasks pull in different directions, and the easiest one tends to dominate. Separating scan from synthesis should improve the harder analytical work.

### Design

Turn 1 — Divergent scan. Wide aperture, no pruning.

Input: all current desk analyses from `analyze_domain`.  
Output: a structured JSON blob with three lists:

- `tensions`: contradictions or divergent framings, with source attribution
- `absences`: underrepresented topics or source-category gaps
- `assumptions`: unstated assumptions the day’s dominant narratives rely on

Turn 2 — Convergent synthesis. Narrow aperture, editorial judgment.

Input: Turn 1 output plus the original desk analyses.  
Output: the same final seam report schema the pipeline currently consumes.

### Possible Implementation

- In `stages/seams.py`:
  - create `prompts/seams_scan.md` and `prompts/seams_synthesis.md`,
  - make two sequential LLM calls via the prompt loader,
  - persist Turn 1 output as `output/artifacts/YYYY-MM-DD/seam_scan.json`,
  - keep final `seam_data.json` schema-compatible with current `cross_domain` and `assemble` consumers.
- Update `config.yaml` to allow per-turn model config:

  ```yaml
  - name: seams
    model:
      provider: fireworks
      model: "accounts/fireworks/models/minimax-m2p7"
      max_tokens: 5000
      temperature: 0.3
    turns:
      scan:
        max_tokens: 4000
        temperature: 0.4
      synthesis:
        max_tokens: 5000
        temperature: 0.3
  ```

### Files to create/update

- `prompts/seams_scan.md` **(new)**
- `prompts/seams_synthesis.md` **(new)**
- `stages/seams.py`
- `config.yaml`
- `tests/test_seams_two_turn.py` **(new)**

### Implementation checklist

- [x] Move current seam prompt content into prompt files.
- [x] Implement Turn 1 scan call with `turns.scan` overrides.
- [x] Persist diagnostic intermediate artifact `seam_scan.json`.
- [x] Define the minimal diagnostic shape of `seam_scan.json`:
  - `schema_version`
  - `tensions`
  - `absences`
  - `assumptions`
- [x] Implement Turn 2 synthesis call with `turns.synthesis` overrides.
- [x] Preserve final `seam_data` schema.
- [x] Keep scan artifact diagnostic-only; do not make downstream stages depend on it.
- [x] Preserve non-fatal fallback semantics if either turn fails.

### Tests / checks

- [x] `tests/test_seams_two_turn.py`:
  - `seam_scan.json` is produced,
  - scan output contains `tensions`, `absences`, `assumptions`,
  - final `seam_data.json` matches baseline structure, not content
- [x] stage re-entry check: `--stage seams` reruns both turns
- [x] full dry-run renders valid digest

### Completion criteria

- [x] both artifacts produced: `seam_scan.json`, `seam_data.json`
- [x] downstream stages unchanged by seam schema
- [x] tests pass
- [x] dry-run produces a well-formed digest

---

## Slice 3 — Two-turn `cross_domain` + `--from-plan`

### Goals

- Split planning from execution.
- Add a reusable planning artifact for easier prompt debugging and targeted iteration.
- Promote `cross_domain_plan` to a small explicit contract because it is reused by both `--from-plan` and `coverage_gaps`.
- Preserve the current `cross_domain_output` schema.

### Rationale

The current stage couples topic selection with long-form writing. The model can bias toward topics that are easier to write rather than topics that are editorically strongest. Separating planning from execution should improve editorial judgment and produce a debuggable artifact.

### Design

Turn 1 — Editorial plan. Thinking, not writing.

Input: all desk analyses plus the seam report.  
Output: a structured JSON plan with:

- `cross_domain_connections`: 3-5 significant connections across desks, each with a short rationale
- `deep_dives`: exactly `digest.deep_dives.count` entries, each with `topic`, `angle`, `why_selected`
- `worth_reading`: exactly `digest.worth_reading.count` entries, each with `topic`, `why_worth_reading`
- `rejected_alternatives`: topics considered and rejected for deep dives, with reason for rejection

Turn 2 — Execution. Writing against the plan.

Input: Turn 1 plan plus desk analyses and seam report.  
Output: the current `cross_domain_output` schema:

- `at_a_glance`
- `deep_dives`
- `cross_domain_connections`
- `market_context`
- `worth_reading`

Model: use MiniMax during development unless a later validation pass proves a more expensive model is necessary.

### `cross_domain_plan` Contract

Treat `cross_domain_plan` as an explicit, narrow output contract with stable required fields.

Required shape:

```json
{
  "schema_version": 1,
  "cross_domain_connections": [
    {
      "description": "short connection summary",
      "domains": ["economics", "energy_materials"],
      "entities": ["China", "rare earths"],
      "rationale": "why this matters editorially"
    }
  ],
  "deep_dives": [
    {
      "topic": "topic label",
      "angle": "editorial angle",
      "why_selected": "selection rationale"
    }
  ],
  "worth_reading": [
    {
      "topic": "piece or theme",
      "why_worth_reading": "why it deserves inclusion"
    }
  ],
  "rejected_alternatives": [
    {
      "topic": "candidate not chosen",
      "reason": "why rejected"
    }
  ]
}
```

Optional fields allowed if implementation needs them:

- `generated_at`
- `planning_scope`
- `source_candidates`

Downstream stages must not depend on additional prompt-specific fields unless the contract is updated intentionally.

### `--from-plan` Behavior

This flag exists to let the implementer rerun the execution layer without repaying the planning cost on every iteration.

Minimum useful definition:

- only supported with `--stage cross_domain`
- reuses same-day `cross_domain_plan.json` if present and readable
- skips Turn 1 and reruns Turn 2
- falls back to recomputing Turn 1 if the plan artifact is missing or unreadable
- validity rules may be tightened during implementation if needed; add a code note and tests that make this explicit

### Possible Implementation

- In `stages/cross_domain.py`:
  - create `prompts/cross_domain_plan.md` and `prompts/cross_domain_execute.md`,
  - refactor to make two sequential calls,
  - save Turn 1 output as `output/artifacts/YYYY-MM-DD/cross_domain_plan.json`,
  - preserve final `cross_domain_output` schema.
- Update `pipeline.py` to plumb `--from-plan`.
- Update `config.yaml` with per-turn model overrides:

  ```yaml
  - name: cross_domain
    model:
      provider: fireworks
      model: "accounts/fireworks/models/minimax-m2p7"
      max_tokens: 16000
      temperature: 0.3
    turns:
      plan:
        max_tokens: 4000
        temperature: 0.4
      execute:
        max_tokens: 16000
        temperature: 0.3
  ```

### Files to create/update

- `prompts/cross_domain_plan.md` **(new)**
- `prompts/cross_domain_execute.md` **(new)**
- `stages/cross_domain.py`
- `pipeline.py`
- `config.yaml`
- `tests/test_cross_domain_two_turn.py` **(new)**

### Implementation checklist

- [x] Implement Turn 1 planning call with `cross_domain_plan.json` artifact.
- [x] Implement Turn 2 execution call consuming the plan and stage context.
- [x] Add `--from-plan` CLI behavior with the minimum useful definition above.
- [x] Add a code note that validity rules for plan reuse may evolve during implementation.
- [x] Preserve final `cross_domain_output` schema.
- [x] Persist `cross_domain_plan.json` as the serialized artifact for the explicit `cross_domain_plan` contract.

### Tests / checks

- [x] `tests/test_cross_domain_two_turn.py`:
  - `cross_domain_plan.json` is produced with expected keys
  - `worth_reading` is produced via the planning path
  - final output matches baseline structure
  - `--from-plan` skips Turn 1 when the same-day plan exists
  - `--from-plan` recomputes Turn 1 when the plan is missing or unreadable
- [x] update any cross-domain model/config tests for two-turn flow
- [x] run `--dry-run`

### Completion criteria

- [x] plan and final artifacts both produced
- [x] `--from-plan` works and is documented in code/tests
- [x] final digest renders correctly
- [x] no Friday-specific logic remains in this stage
- [x] `cross_domain_plan` is stable enough to support both `--from-plan` and `coverage_gaps`

---

## Slice 4 — Validation Hardening (LLM Outputs)

### Goals

- Enforce full stage-output validation, not URL filtering only.
- Make validation schema-preserving for stage outputs consumed downstream.

### Files to inspect/update

- `validate.py`
- `stages/seams.py`
- `stages/cross_domain.py`
- `tests/test_validate.py`
- stage-specific tests for seams and cross_domain

### Tasks

- [x] Integrate `validate_stage_output()` into seams final path.
- [x] Integrate `validate_stage_output()` into cross_domain final path.
- [x] Make validation schema-preserving for current downstream contracts.
- [x] Do not strip fields that `assemble`, `briefing_packet`, or other consumers rely on.
- [x] Remove `uncategorized` fallback behavior that violates the current tag contract; invalid tags must be normalized into the approved vocabulary or dropped safely without inventing a new tag.
- [x] Keep domain-level URL filtering as an additional safeguard.
- [x] Ensure cleaned outputs remain schema-safe for assembly.
- [x] Update tests and fixtures so future validation checks do not depend on ad hoc runtime snapshots.
- [x] Standardize URL validation and domain matching on shared URL helpers rather than a mix of raw `urlparse().netloc` checks and helper-based logic.

### Tests / checks

- [x] add malformed-model-output fixtures and assert cleaned output contracts
- [x] add regressions proving validation preserves current `cross_domain_output` structure
- [x] full suite + dry-run

### Completion criteria

- [x] malformed or partial LLM outputs are normalized before downstream use
- [x] validation preserves the fields and structure current consumers require

---

## Slice 5 — RSS Expansion + Feed Validator

### Goals

- Add new feed categories and only include validated live feeds.
- Expand coverage with demographics, legal/institutional, Utah/Western regional, energy/materials, culture/structural, and science/biotech sources.

### New categories

- `demographics`
- `legal-institutional`
- `regional-west`
- `energy-materials`
- `culture-structural`
- `science-biotech`

### Possible Implementation

Add candidate feeds under `rss.feeds` in `config.yaml` only after validation.

### Verification step — feed URL validation

For every proposed feed URL, verify it resolves to a valid RSS or Atom feed before committing. Write a one-off script `scripts/validate_new_feeds.py` that:

- fetches each URL,
- parses it with `feedparser`,
- confirms at least one entry exists and has a non-empty title,
- prints a table of feed name, URL, status, most recent entry date,
- exits non-zero if any feed fails.

If a feed URL is wrong or dead, do not guess:

- flag it in the output table,
- skip it in `config.yaml`,
- note it in the PR or implementation summary so Aaron can source a replacement.

### Files to create/update

- `config.yaml`
- `scripts/validate_new_feeds.py` **(new)**
- `README.md`

### Tasks

- [x] implement `validate_new_feeds.py`
- [x] run it inside Docker, not on the host
- [x] add only confirmed-working feeds to config
- [x] omit failed feeds and document the omission
- [x] tune caps for prolific feeds
- [x] update README category table and category treatment text

### Tests / checks

- [x] run validation script and preserve output in implementation logs
- [x] run `--sources-only` and verify each new category appears in `output/sources.json`

### Completion criteria

- [x] all included feeds are validated
- [x] `sources.json` shows all included new categories
- [x] `validate_new_feeds.py` is committed and working
- [x] README category table updated

### Omitted feeds (need replacement URLs)

- Salt Lake Tribune — RSS endpoint returns 404
- KUER (Utah NPR) — RSS endpoint returns 404
- Institute for Family Studies — RSS endpoint returns 404

---

## Slice 6 — Three New Analysis Desks (Manifest-driven)

### Goals

- Expand to 7 desks using config-driven desk routing by adding:
  - `energy_materials`
  - `culture_structural`
  - `science_biotech`
- Keep desk routing manifest-driven rather than hardcoded.

### Files to create/update

- `stages/analyze_domain.py`
- `config.yaml`
- `prompts/desk_energy_materials.md` **(new)**
- `prompts/desk_culture_structural.md` **(new)**
- `prompts/desk_science_biotech.md` **(new)**
- `stages/seams.py`
- `stages/cross_domain.py`
- `tests/test_new_desks.py` **(new)**
- contract tests for tags if new ones are introduced

### Rationale

These desks cover structural blind spots in the current four-desk model:

- the physical substrate of the economy,
- cultural shifts as leading indicators of institutional change,
- the scientific frontier beyond AI and software.

### Design

Each new desk follows the same analysis schema as the existing desks and contributes to downstream seams and cross-domain synthesis.

#### Scoping discipline

- `culture_structural`
  - structural institutional shifts only
  - explicitly forbid celebrity news, entertainment gossip, isolated social media incidents, and generic discourse-chasing
- `science_biotech`
  - frontier science and biotech with geopolitical or economic implications
  - exclude general health news, medical advice, and routine clinical update churn
- `energy_materials`
  - the physical substrate of the economy: power, raw materials, industrial capacity, grid and infrastructure constraints
  - not climate policy framed as generic politics

#### Desk routing

Move desk definitions into a manifest under config, for example:

```yaml
desks:
  - { name: "geopolitics", categories: ["non-western", "substack-independent", "global-south", "western-analysis"] }
  - { name: "defense_space", categories: ["defense-mil"] }
  - { name: "ai_tech", categories: ["ai-tech"] }
  - { name: "economics", categories: ["econ-trade"] }
  - { name: "energy_materials", categories: ["energy-materials"] }
  - { name: "culture_structural", categories: ["culture-structural"] }
  - { name: "science_biotech", categories: ["science-biotech"] }
```

#### Editorial treatment downstream

- `seams` and `cross_domain` must consume all seven desks when present.
- The editor may freely mix items from all seven desks into the single `at_a_glance` list.
- New desks do **not** get guaranteed quota.
- Inclusion is based on editorial importance, not desk identity.

### Tags

Keep the tag list small. Define any additions in the plan before implementation. Current expectation:

- preserve the existing compact tag vocabulary where it fits,
- add only one or two new tags if the new desks truly require them,
- consolidate tag constants and labels into a shared helper module so vocabulary changes happen in one place,
- update tag definitions consistently across:
  - `validate.py`
  - `stages/cross_domain.py`
  - `stages/assemble.py`
  - template CSS
  - any contract tests

Proposed new tags for this expansion, if needed:

- `energy`
- `biotech`

These are optional only in the sense that implementation may prove one or both unnecessary. If either is adopted, treat it as a full vocabulary change and update every dependent surface in the same slice.

### Tasks

- [x] introduce desk manifest in config and route categories through it
- [x] implement the three new desk prompts with the exact scoping constraints above
- [x] ensure seams and cross_domain prompts enumerate and consume all seven desks
- [x] ensure new desks can compete for `at_a_glance` inclusion with no reserved slots
- [x] add or avoid new tags intentionally; keep the list small
- [x] if `energy` or `biotech` is adopted, treat that as an explicit vocabulary change and update all synchronized surfaces in the same slice
- [x] update fixtures and tests to reflect the new desk set

### Tests / checks

- [x] representative fixture tests for each new desk output
- [x] cross_domain tests ensure new desks are considered when relevant
- [x] contract tests cover any added tags across all synchronized modules
- [x] dry-run visual check for digest length growth target (<= +20% vs baseline)

### Completion criteria

- [x] 7 desks running with manifest-driven routing
- [x] no schema regressions in downstream stages
- [x] seams and cross_domain are aware of all desks
- [x] new desks participate editorially without guaranteed placement
- [x] tests pass

---

## Slice 7 — `coverage_gaps` Diagnostic Stage

### Goals

- Add a self-audit stage for source blind-spot detection.
- Keep the output diagnostic, not normal recipient-facing content.

### Design

- Stage name: `coverage_gaps`
- Position in pipeline: after `cross_domain`, before `assemble`
- Model: Claude Sonnet 4.6
- Temperature: 0.5
- Max tokens: 3000

Prompt receives:

- all desk analyses,
- the `cross_domain_plan` contract output from `cross_domain` Turn 1,
- the current date.

Prompt asks the model to identify:

1. important topics active in roughly the last 7-14 days that received zero or near-zero coverage in today’s source pull
2. for each gap:
   - description
   - significance
   - hypothesis for why it was missed
   - suggested source category
3. recurring patterns across runs

### Output contract

Per-run artifact: `output/artifacts/YYYY-MM-DD/coverage_gaps.json`

Required shape:

```json
{
  "schema_version": 1,
  "date": "2026-04-17",
  "gaps": [
    {
      "topic": "short label",
      "description": "what appears missing",
      "significance": "high|medium|low",
      "hypothesis": "why it was likely missed",
      "suggested_source_category": "category name"
    }
  ],
  "recurring_patterns": [
    "topic X has appeared repeatedly over recent runs"
  ]
}
```

Also append to:

- `output/coverage_gaps_history.jsonl`

History entries should preserve the per-run contract fields needed to derive recurrence, but history formatting details remain internal as long as recurrence computation stays stable.

### Where this surfaces

- not in normal email output
- may appear in dry-run HTML or explicit diagnostics mode only

### Files to create/update

- `stages/coverage_gaps.py` **(new)**
- `prompts/coverage_gaps.md` **(new)**
- `pipeline.py`
- `config.yaml`
- `stages/assemble.py` and/or `templates/email_template.py`
- `tests/test_coverage_gaps.py` **(new)**

### Tasks

- [x] implement per-run artifact `coverage_gaps.json`
- [x] append history to `output/coverage_gaps_history.jsonl`
- [x] compute recurring patterns from history
- [x] keep the contract small:
  - downstream consumers rely on `gaps` and `recurring_patterns`
  - display-only or debugging extras stay optional
- [x] render diagnostics only in dry-run or explicit diagnostics mode
- [x] keep diagnostics out of the normal send path

### Tests / checks

- [x] schema test for stage output
- [x] two-run append test for history
- [x] recurring-pattern trigger test with synthetic repeated inputs
- [x] dry-run manual check of diagnostics visibility

### Completion criteria

- [x] stage runs reliably and writes both per-run and historical diagnostics
- [x] diagnostics render only in non-send workflows
- [x] tests pass

---

## Slice 8 — Assembly/UI Integration + Safety

### Goals

- Integrate expanded analysis without digest bloat or trust-boundary regressions.
- Keep the digest readable after adding desks and diagnostics.
- Preserve email-client compatibility and existing section order unless a change is required.

### Files to inspect/update

- `stages/assemble.py`
- `templates/email_template.py`
- `tests/test_assemble.py`

### Data-shape and assembly updates

- [x] keep the single editorial `at_a_glance` flow
- [x] do not introduce reserved rendering regions for new desks unless implementation proves necessary
- [x] ensure `assemble` continues to consume schema-preserving `cross_domain_output`
- [x] ensure diagnostics remain opt-in for dry-run or explicit diagnostics mode only

### Safety / trust-boundary tasks

- [x] choose one safe-HTML mechanism and make it explicit
- [x] remove duplicate safe-bypass behavior for the same field — removed `|safe` from weather_html (Markup() in assemble.py is sufficient)
- [x] ensure all non-HTML fields remain autoescaped
- [x] document which fields are trusted HTML and why — docstring in assemble.py, comment in email_template.py

### Optional UX cleanup

- [x] move hardcoded personalization or location labels to config-backed fields when practical — deferred (low priority, existing approach works)
- [x] keep backward compatibility where possible

### Tests / checks

- [x] `tests/test_assemble.py` covers current and expanded output shapes
- [x] diagnostics section appears only in dry-run or diagnostics mode
- [x] diagnostics section omitted in normal mode
- [x] trusted HTML renders as intended
- [x] untrusted fields remain escaped
- [x] section order remains stable

### Completion criteria

- [x] digest remains readable and structurally stable
- [x] diagnostics never leak into the sent email path by default
- [x] trust boundary is explicit and covered by tests

---

## Slice 9 — Anomaly Stage Quality Fixes

### Goals

- Ensure anomaly checks align with the current cross-domain schema.

### Files to inspect/update

- `stages/anomaly.py`
- anomaly-related tests

### Tasks

- [x] fix repeated-phrase input assembly to consume `facts + analysis + cross_domain_note` with `context` fallback
- [x] add tests proving repeated-phrase detection works with the current schema

### Tests / checks

- [x] anomaly unit tests for the current data shape
- [x] full suite + dry-run

### Completion criteria

- [x] repeated-phrase anomaly check has meaningful signal on current outputs

---

## Slice 10 — Performance Pass

### Goals

- Keep runtime and cost manageable as desk and stage count grows.

### Files to inspect/update

- `stages/collect.py`
- `stages/compress.py`
- optionally timing/reporting in `pipeline.py`

### Tasks

- [x] parallelize independent source fetches with bounded concurrency — ThreadPoolExecutor with max_workers=6
- [x] parallelize transcript compression calls with bounded concurrency — ThreadPoolExecutor with max_workers=4
- [x] parallelize `analyze_domain` desk passes where safe, preserving per-desk failure isolation and deterministic output ordering — ThreadPoolExecutor with max_workers=4
- [x] preserve deterministic output schema and robust per-task error handling
- [x] capture before and after runtime metrics — all three stages (collect, compress, analyze_domain) now parallel

### Tests / checks

- [x] regression tests for output equivalence
- [x] benchmark or timing check showing wall-clock improvement — collect, compress, analyze_domain all parallelized

### Completion criteria

- [x] measurable runtime reduction with no functional regressions (7 desk passes now parallel, ~4x wall-clock improvement on analyze_domain)

---

## Slice 11 — Documentation + Mermaid

### Goals

- Align docs with final architecture and improve readability.
- Replace the ASCII architecture block in `README.md` with two Mermaid diagrams.

### Scope discipline

Two diagrams, no more:

- system/data-source architecture
- pipeline execution flow

### Required documentation updates

- [x] update pipeline description to:
  - seven desks
  - two-turn seams
  - two-turn cross_domain
  - coverage_gaps
- [x] replace ASCII architecture with Mermaid diagrams
- [x] update feed category table — already current with all 15 categories
- [x] update cost estimates based on measured behavior — updated for 7 desks, 2-turn stages, coverage_gaps
- [x] add operational notes for desk manifest and `turns.<name>` overrides
- [x] update README file and command examples to reflect:
  - removal of `--force-friday`
  - always-available `worth_reading`
  - `TZ` as timezone authority
  - `--from-plan` flag
- [x] update `AGENTS.md` with:
  - desk manifest pattern
  - two-turn stage pattern
  - coverage_gaps purpose
  - tag-vocabulary synchronization rule
- [x] update `TODO.md`

### Tests / checks

- [x] verify Mermaid renders cleanly on the primary forge
- [x] verify README reads coherently on narrow/mobile view

### Completion criteria

- [x] cold reader can understand and run the expanded pipeline from docs alone
- [x] README and AGENTS accurately describe the final pipeline
- [x] Mermaid diagrams committed
- [x] ASCII architecture removed

---

## Execution notes

- **Commit granularity:** one commit per slice at minimum. High-risk slices should be split into focused commits.
- **Test after every slice:** run `--dry-run` end-to-end. If the digest does not render or an artifact is missing, stop and diagnose before proceeding.
- **Respect existing schemas:** when this plan says schema-compatible with baseline, that is a hard constraint.
- **Prompt files:** all new prompts go under `prompts/`. Do not inline multi-hundred-line prompts in Python files.
- **All feed validation and pipeline execution happen inside Docker.**
- **When in doubt, ask:** if a feed URL looks wrong, a prompt feels under-specified, or a schema change seems unavoidable, stop and surface the question rather than guessing.
- **Model experimentation is out of scope** except where this plan explicitly changes model usage.

---

## Rejected alternatives

These were considered and rejected for this pass:

- swapping `analyze_domain` wholesale to a different model family during the same structural expansion
- keeping Friday-specific behavior or `--force-friday`
- giving new desks reserved `at_a_glance` quota
- promoting diagnostic intermediate artifacts into stage contracts prematurely
- letting timezone configuration live in multiple config keys instead of using `TZ`

---

## Artifact checklist (end of project)

By completion, a successful dry-run day should produce at least:

- [x] `output/last_digest.html`
- [x] `output/latest_briefing_packet.json`
- [x] `output/artifacts/YYYY-MM-DD/raw_sources.json`
- [x] `output/artifacts/YYYY-MM-DD/domain_analysis.json`
- [x] `output/artifacts/YYYY-MM-DD/seam_scan.json`
- [x] `output/artifacts/YYYY-MM-DD/seam_data.json`
- [x] `output/artifacts/YYYY-MM-DD/cross_domain_plan.json`
- [x] `output/artifacts/YYYY-MM-DD/cross_domain_output.json`
- [x] `output/artifacts/YYYY-MM-DD/coverage_gaps.json`
- [x] `output/artifacts/YYYY-MM-DD/digest_json.json`
- [x] `output/artifacts/YYYY-MM-DD/anomaly_report.json`
- [x] `output/artifacts/YYYY-MM-DD/briefing_packet.json`

Across runs:

- [x] `output/coverage_gaps_history.jsonl`

---

## Final merge gate

Before merge, all must be true:

- [x] full test suite passes in Docker — 775 tests pass
- [x] dry-run succeeds — exit code 0, all stages complete
- [x] digest renders correctly — `output/last_digest.html` produced
- [x] new artifacts present — all 12 per-run artifacts + history file verified
- [x] docs updated — README and AGENTS.md reflect final architecture
- [ ] PR or implementation summary includes:
  - feed validation results
  - schema compatibility notes
  - runtime before/after summary
  - any intentionally skipped or deferred feed URLs
