# Stage Contract Hardening Plan

Date: 2026-04-22

## Problem

Pipeline stages currently exchange nested `dict` / `list` artifacts through
`context`. The schemas are real, but mostly implicit: they are spread across
prompts, validators, templates, tests, and downstream stage assumptions. That
means a source or RSS enrichment change can create malformed downstream shapes
that degrade quietly instead of failing close to the cause.

The immediate risk is not Python type aesthetics. The risk is silent schema
drift: missing `item_id`, renamed `connection_hooks`, malformed `links`, or a
changed deep-dive flag can make later stages behave as though good source data
does not exist.

## Strategy

Keep the pipeline's persisted artifacts as JSON-compatible dicts for now, but
add typed contract normalization at high-risk stage boundaries. The first pass
should be permissive about optional fields and strict about container shape, so
old artifacts continue to load while meaningful drift becomes visible in logs
and tests.

Because Pydantic is not currently a project dependency, the first slice uses
standard-library dataclasses and explicit normalizers. If the contract layer
grows enough to justify Pydantic, the model internals can be swapped later while
keeping the same stage-facing helper functions.

## Phases

### Phase 1 — Domain Analysis Boundary

Status: implemented 2026-04-22.

- Add contract models/normalizers for:
  - `SourceLink`
  - `ConnectionHook`
  - `DomainItem`
  - `DomainResult`
  - `DomainAnalysis`
- Validate/normalize each `analyze_domain` desk result after the LLM call and
  URL filtering.
- Preserve the existing dict artifact shape with `model_dump()`-style helpers.
- Add tests for malformed desk output:
  - non-list `items`
  - non-dict item entries
  - malformed `links`
  - malformed `connection_hooks`
  - boolean-like `deep_dive_candidate`
  - missing optional fields
- Add a small artifact validation script for `domain_analysis.json`.

### Phase 2 — Seams Boundary

Status: implemented 2026-04-22.

- Validate `domain_analysis` before seam candidate and annotation logic reads
  item IDs or links.
- Validate `seam_candidates`, `seam_annotations`, and legacy `seam_data`.
- Add tests that renamed/missing item IDs are reported before seam annotations
  silently collapse.

Implementation notes:

- `seams.run()` now normalizes `domain_analysis` again at the stage boundary so
  cached or manually edited artifacts are checked before item IDs and links are
  consumed.
- `seam_candidates` and `seam_annotations` are normalized before the existing
  semantic pruning/evidence gates run.
- `seam_contract_issues` records non-fatal contract drift as a sidecar artifact.
- `scripts/validate_artifacts.py` now validates optional seam artifacts when
  they are present next to `domain_analysis.json`.

Verification: focused Dockerized Phase 2 suite passed (`34 passed`).

### Phase 3 — Cross-Domain Boundary

- Implemented `CrossDomainPlan` and `CrossDomainOutput` normalizers in
  `morning_digest/contracts.py`.
- `cross_domain` now normalizes fresh and reused plans before execution.
- Execute output is normalized before URL/editorial validation.
- `cross_domain_contract_issues` records non-fatal drift from plan, output, or
  boundary `domain_analysis` input.
- `scripts/validate_artifacts.py` now validates optional
  `cross_domain_plan.json` and `cross_domain_output.json`.
- Covered `at_a_glance`, `deep_dives`, `worth_reading`, and
  `cross_domain_connections`.

Verification: focused Dockerized Phase 3 suite passed (`46 passed`).

### Phase 4 — Assemble Boundary

- Implemented render-boundary normalization for `cross_domain_output`,
  fallback `domain_analysis`, and `seam_annotations`.
- Malformed or empty cross-domain output can now degrade to normalized
  `domain_analysis` before template rendering.
- `assemble_contract_issues` records non-fatal render-boundary drift, and
  `digest_json` preserves those issues for artifact inspection.

Verification: focused Dockerized Phase 4 suite passed (`102 passed`).

### Phase 5 — Tightening

- Review historical artifacts with the validation script.
- Decide which extra fields should be preserved and which should be rejected.
- Consider replacing the dataclass normalizers with Pydantic if validation
  complexity grows.

## Acceptance Criteria For Phase 1

- Done — `analyze_domain` emits the same artifact shape for valid output.
- Done — malformed optional nested structures normalize safely.
- Done — invalid top-level shape returns a safe empty result and logs a contract issue.
- Done — existing downstream tests continue to pass.
- Done — `scripts/validate_artifacts.py` can validate saved `domain_analysis.json`
  artifacts directly.

Phase 1 verification: Dockerized full suite passed after implementation
(`917 passed`).
