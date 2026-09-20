# Fix Run Mode Semantics and Add Missing Acceptance Tests

- **ID:** 0534
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0529, 0530, 0531, 0532, 0533

## Problem

A validation run without `--live` currently writes `run_type="acceptance"` even though it cannot activate (no repeatability run is present), making the label misleading and potentially confusing tooling or dashboards that key on `run_type`. Separately, the test suite lacks coverage for a range of failure modes that were identified during architecture review: DB-lock rollback, stale contract invalidation, config corruption, duplicate record IDs, missing interaction values, tie handling, divergence subgroup minimums, and the critical prompt-identity invariant between the validator and production scorer.

## Proposed approach

- Rename the non-`--live` mode to `run_type="dry_run"` or `"deterministic_validation"`; reserve `"acceptance"` exclusively for runs that use `--live`, the configured N from `validation_config.json`, and pass all required tests.
- Add explicit tests for each of the following:
  - DB-lock acquired during activation is rolled back cleanly on failure
  - Stale scorer contract (0531) causes `_accepted_dim_state()` to return `usable=False`
  - Malformed `validation_config.json` aborts the run with a fatal error (not defaults)
  - Duplicate `record_id` on insert raises a fatal error (complements 0533)
  - Missing `rate_interaction` values are excluded, not coerced (complements 0532)
  - Tie outcome is reported separately, not counted as a base win
  - Divergence subgroup below `MIN_SUBGROUP_N` suppresses win-rate reporting
  - Validator-generated LLM request is byte-identical to production request for the same ticker/evidence fixture (complements 0529)
- Fix the stale docstring that says "batches tickers in groups of 8" (production currently uses `BATCH = 1`).

## Touches

- `validate_macro_scorer.py` (run_type assignment, docstring)
- Test suite (new tests as listed above)

## Done when

- [ ] `run_type="acceptance"` is emitted only for `--live` runs with configured N and all required tests passing
- [ ] Non-`--live` runs emit `run_type="dry_run"` (or equivalent) in artifact and DB
- [ ] Explicit tests exist for all eight failure/edge-case scenarios listed above
- [ ] Stale "groups of 8" docstring is corrected
- [ ] Full test suite passes with no regressions

## Review — 2026-09-20

Partially implemented in 4dbb0c0. Dry-run labeling exists, but acceptance is selected before the final verdict. Explicit DB-lock rollback and per-component stale-contract tests are absent, and prompt identity coverage does not compare the two call paths. Complete the listed edge-case tests and full regression verification.
