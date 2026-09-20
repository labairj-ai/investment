# Authoritative Observation Count

- **ID:** 0425
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0424

## Problem

`score_for_observe()` uses `INSERT OR IGNORE` for each observation row and increments
`n_written` unconditionally — so if 3 of 20 inserts are silently ignored (duplicate episode_id
for the same model_version), `scored_candidates` is still recorded as 20. The ledger then
reports COMPLETED with `expected == scored`, but 3 rows never actually landed in
`model_observations`. The coverage check believes the sweep is complete when it is not.

Additionally, `completed_at` is set to a plain date string in some paths rather than a full
ISO timestamp, making it inconsistent with `started_at`.

## Proposed approach

- After all inserts complete, run:
  ```sql
  SELECT COUNT(*) FROM model_observations
  WHERE model_version = ? AND decision_cohort_id = ?
  ```
  and use that count as `scored_candidates` rather than the attempted-insert counter.
- Set ledger `status` to `COMPLETED` only when `actual_count == expected_count`.
  When `actual_count < expected_count` (and no error occurred), set status to `PARTIAL`.
- Ensure `completed_at` is always a full ISO 8601 timestamp (not just a date).
- Update `_check_candidate_coverage()` in `check_integrity.py` to treat PARTIAL status rows
  as a coverage gap (WARN at minimum; consider BLOCK when delta is large).

## Touches

- `agents/learning/challenger.py` — replace `n_written` counter with post-insert COUNT(*) query; PARTIAL status
- `check_integrity.py` — handle PARTIAL status in coverage check
- `tests/test_calibration.py` — test PARTIAL status when INSERT OR IGNORE silently drops rows

## Done when

- [ ] `scored_candidates` reflects actual persisted rows, not attempted inserts
- [ ] `status = 'PARTIAL'` when actual count < expected count (and no exception)
- [ ] `completed_at` is always a full ISO timestamp
- [ ] PARTIAL rows surface as a coverage gap in `_check_candidate_coverage()`
