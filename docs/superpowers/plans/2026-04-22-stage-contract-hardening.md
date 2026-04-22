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

- Validate `domain_analysis` before seam candidate and annotation logic reads
  item IDs or links.
- Validate `seam_candidates`, `seam_annotations`, and legacy `seam_data`.
- Add tests that renamed/missing item IDs are reported before seam annotations
  silently collapse.

### Phase 3 — Cross-Domain Boundary

- Add contracts for `CrossDomainPlan` and `CrossDomainOutput`.
- Validate plan output before execution.
- Validate final cross-domain output before URL/editorial validation.
- Cover `at_a_glance`, `deep_dives`, `worth_reading`, and
  `cross_domain_connections`.

### Phase 4 — Assemble Boundary

- Validate or normalize `cross_domain_output`, fallback `domain_analysis`, and
  `seam_annotations` before template rendering.
- Keep degraded rendering behavior, but make degraded input explicit in logs or
  diagnostics.

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

Verification: Dockerized full suite passed after Phase 1 implementation
(`917 passed`).
