# Fix Canary Phase Semantics and Cohort Invariant

- **ID:** 0439
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0435

## Problem

The canary's PAPER_ACTIVE parity check queries the model's *current* `lifecycle_state` to decide
whether variant parity is required. If a model was PAPER_ACTIVE during the audited sweep but has
since been suspended, the canary skips the parity check entirely — silently passing what should be
a verified assertion. The correct signal is the sweep's own `phase` column in
`learning_sweep_runs`, not the model's current state.

Additionally, the invocation audit groups ledger rows by `agent_run_id` but never asserts that all
those rows share a single `cohort_id`. The architecture requires exactly one cohort per OH
invocation; without this check the invariant is assumed rather than enforced.

## Proposed approach

- **Phase-based parity check:** In the per-model loop of the invocation audit, replace the
  `SELECT lifecycle_state FROM learning_models WHERE model_version=…` query with the
  `phase` column already present on the `learning_sweep_runs` row being iterated. Require variant
  parity when `phase = 'PAPER_ACTIVE'`.
- **Single-cohort invariant:** After fetching all ledger rows for the `agent_run_id`, add:
  `SELECT COUNT(DISTINCT cohort_id) FROM learning_sweep_runs WHERE agent_run_id=…`
  and assert the result equals 1. Fail immediately if not.
- Remove or repurpose the now-redundant `lifecycle_state` lookup inside the loop.
- Question: if `phase` is NULL for older rows (pre-phase column), fall back to `lifecycle_state`
  query or skip gracefully?

## Touches

- `scripts/canary_audit.sh`
- `tests/test_calibration.py`

## Done when

- [ ] Variant parity check uses `learning_sweep_runs.phase` not `learning_models.lifecycle_state`
- [ ] A sweep recorded under PAPER_ACTIVE phase triggers parity check even if model is now SUSPENDED
- [ ] Canary asserts `COUNT(DISTINCT cohort_id) = 1` per agent_run_id invocation
- [ ] A multi-cohort invocation (structural bug) causes canary exit 1
