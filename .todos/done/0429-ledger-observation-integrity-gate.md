# Ledger/Observation Integrity Gate

- **ID:** 0429
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0424, 0425

## Problem

The promotion and degradation gates (`_check_promotion_gates()`, `_check_degradation()`) read
`model_observations` rows to measure prospective evidence. But there is currently no gate that
verifies those observations came from complete, ledger-confirmed sweeps. A model could
accumulate `model_observations` rows from PARTIAL or FAILED sweeps — or from sweeps with no
ledger row at all (pre-0418 rows) — and those partial cohorts would still count toward the
OBSERVE→PAPER_ACTIVE gate thresholds and degradation decisions.

## Proposed approach

- In `check_integrity.py` (or directly in promotion/degradation gate checks), add a health
  condition for OBSERVE/PAPER_ACTIVE/SUSPENDED models:
  - Every cohort referenced in `model_observations` (by `decision_cohort_id`) should have a
    corresponding COMPLETED (not PARTIAL, FAILED, or missing) row in `learning_sweep_runs`.
  - Cohorts with no ledger row are treated as pre-0418 legacy and are allowed (WARN, not BLOCK)
    until they age out of the evaluation window.
  - Cohorts with PARTIAL or FAILED ledger rows are flagged as BLOCK: their observations are
    not eligible for promotion or degradation calculations.
- Surface the blocked cohort count in `learning_readiness_report()` as
  `ineligible_cohorts_ledger` so operators can see how much prospective data is excluded.
- This gate does not require backfilling pre-0418 rows — it applies forward from when
  `learning_sweep_runs` is reliably populated.

## Touches

- `check_integrity.py` — new `_check_ledger_observation_consistency()` check
- `agents/learning/calibration.py` — promotion/degradation gates filter on COMPLETED ledger cohorts
- `tests/test_calibration.py` — PARTIAL sweep cohort excluded from gate counts

## Done when

- [ ] `_check_candidate_coverage()` (or a new check) flags cohorts with PARTIAL/FAILED ledger rows
- [ ] Promotion gates exclude observations from non-COMPLETED ledger cohorts
- [ ] Degradation gate excludes observations from non-COMPLETED ledger cohorts
- [ ] Pre-0418 legacy cohorts (no ledger row) produce WARN, not BLOCK
- [ ] `learning_readiness_report()` surfaces `ineligible_cohorts_ledger` count
