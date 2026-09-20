# Invalidate Acceptance Automatically on Scorer Contract Change

- **ID:** 0531
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0529

## Problem

`macro_acceptance_state` records the model identity and commit SHA, but `_accepted_dim_state()` only looks up the active `record_id` — it does not verify that the scorer currently running is the same scorer that was accepted. A change to the prompt template, model, evidence schema, dimension definitions, aggregation logic, or temperature can be deployed while the old acceptance continues granting `usable=True`. Commit SHA is too sensitive as a compatibility key (a UI-only change would invalidate the scorer), so a content-addressed hash over only the scoring contract components is needed instead.

## Proposed approach

- Define `scorer_contract_hash` as a deterministic hash over: model identity, prompt template, `MACRO_DIMS` definitions, evidence-schema version, scoring-schema version, temperature, and aggregation logic/version identifier.
- Add `scorer_contract_hash` column to `macro_acceptance_state` and `macro_dimension_validation`; populate at acceptance time.
- In `_accepted_dim_state()`, compute the current `scorer_contract_hash` at call time and compare to the stored value on the active acceptance record. On mismatch, return `usable=False` with `reason="acceptance_stale_scorer_contract"`.
- Keep `commit_sha` as a provenance field only — never use it as a compatibility gate.
- Add a test that mutates each component covered by the hash (prompt text, model id, a dimension definition, temperature) and asserts `_accepted_dim_state()` returns `usable=False` after each mutation without re-running acceptance.

Open question: should `scorer_contract_hash` be computed from source code strings at import time, or from a versioned config artifact written at acceptance time? The latter is more stable across refactors.

## Touches

- `validate_macro_scorer.py` (`_accepted_dim_state`, acceptance write path, hash computation)
- DB schema migration (add `scorer_contract_hash` to `macro_acceptance_state` and `macro_dimension_validation`)
- Production scoring path (must compute and store hash on every score row for future auditability)
- Test suite (contract-mutation invalidation tests)

## Done when

- [x] `scorer_contract_hash` is persisted in `macro_acceptance_state` at acceptance time
- [x] `_accepted_dim_state()` computes the current hash and returns `usable=False` with `reason="acceptance_stale_scorer_contract"` on mismatch
- [x] Commit SHA is retained as provenance but not used as a compatibility gate
- [x] Test confirms each hash-covered component independently triggers invalidation when changed
- [x] Production scoring stores the hash so accepted vs. runtime contract can be compared in the audit trail

## Review — 2026-09-20

Partially implemented in 4dbb0c0. Acceptance hash comparison exists, but production score rows do not store scorer_contract_hash, and tests do not mutate each contract component independently. The hash also lacks an explicit evidence-schema and aggregation-version component.

## Completion — 2026-09-20

Completed remaining implementation and behavioral coverage in `tests/test_macro_contract_completion.py`. Numeric thresholds, full-N gating, frozen evidence/prompt provenance, contract invalidation, UUID run persistence, timestamp exclusion, and atomic activation are verified. Historical review notes above describe the prior implementation.
