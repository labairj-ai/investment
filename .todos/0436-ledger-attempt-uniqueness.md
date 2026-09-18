# Enforce One Ledger Row Per Model/Cohort Pair

- **ID:** 0436
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0430

## Problem

`learning_sweep_runs` has no uniqueness constraint on `(model_version, cohort_id)`. If the same model/cohort pair is ever scored twice (a retry, a bug, or a double-fire of the OH trigger), both `eligible_learning_cohorts()` and `_ineligible_ledger_cohorts()` can include the same cohort — one helper's query matches the COMPLETED row, the other matches the FAILED row. The helpers become ambiguous and the provenance contract breaks silently.

## Proposed approach

- **Decision on retry semantics:** A cohort ID is a UUID generated per OH invocation per model, representing a specific prospective prediction event. It should never be reused. A retry is a new event and must get a new cohort ID.
- **Schema change:** Add `UNIQUE(model_version, cohort_id)` to `learning_sweep_runs`. Write a migration script or `agent_db.py` schema update.
- **Application enforcement:** In `score_for_observe()`, the STARTED INSERT will then raise naturally on duplicate — which is already fail-closed (0424). No other application change needed.
- **Helper simplification:** Once uniqueness is enforced, `eligible_learning_cohorts()` and `_ineligible_ledger_cohorts()` are guaranteed non-overlapping. Document this invariant in both functions.
- **Open question:** Should old duplicate rows (if any exist in the live DB) be cleaned up, or just left as historical data with the constraint applied going forward? Safe approach: apply constraint only; don't delete any rows.

## Touches

- `agent_db.py` — schema migration to add UNIQUE constraint
- `agents/learning/challenger.py` — no code change needed (INSERT already fail-closed)
- `agents/learning/calibration.py` — update docstrings on `eligible_learning_cohorts()` and `_ineligible_ledger_cohorts()` to note uniqueness invariant
- `tests/test_calibration.py` — test that duplicate cohort insert raises

## Done when

- [ ] `UNIQUE(model_version, cohort_id)` constraint exists on `learning_sweep_runs`
- [ ] Migration applied to live DB on optiplex without data loss
- [ ] `eligible_learning_cohorts()` and `_ineligible_ledger_cohorts()` docstrings note the non-overlap guarantee
- [ ] Test confirms that a second `score_for_observe()` call with the same cohort_id raises
