# Preserve Hysteresis Anchor When Snapshot Already Exists for Today

- **ID:** 0394
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** none

## Problem

`_check_degradation()` uses `INSERT OR IGNORE` with a `(model_version, snapshot_date)` UNIQUE constraint. If `_check_degradation()` is called twice in the same day (e.g. outcome labeler runs twice), the second call recomputes `current_max_labeled_at` but silently drops it because the INSERT is ignored. The `last_outcome_labeled_at` column in the existing row is never updated, so the hysteresis anchor freezes at the first run's value. Subsequent invocations see a stale anchor and count observations already included in the previous snapshot as "new", potentially firing a second snapshot prematurely.

## Proposed approach

- Replace `INSERT OR IGNORE` with `INSERT OR REPLACE` (or use `INSERT ... ON CONFLICT DO UPDATE SET last_outcome_labeled_at=excluded.last_outcome_labeled_at, ...`) so that re-runs on the same day update the anchor without duplicating the row.
- Alternatively, check before inserting: if a row already exists for today, `UPDATE` only the anchor columns rather than re-inserting metric columns.
- Preferred: use `INSERT ... ON CONFLICT(model_version, snapshot_date) DO UPDATE SET last_outcome_labeled_at=excluded.last_outcome_labeled_at, last_snapshot_max_obs_id=excluded.last_snapshot_max_obs_id` to update anchor without overwriting the original metrics.
- Add a test that calls `_check_degradation` twice in one day and asserts the anchor reflects the second call's data.

## Touches

- `agents/learning/calibration.py` — `_check_degradation()` lines ~1423-1436
- `tests/test_calibration.py` — `TestOutcomeTimeHysteresis0384`

## Done when

- [ ] Second same-day call to `_check_degradation` updates `last_outcome_labeled_at` in the existing snapshot row
- [ ] Metric columns (spread, MAE, verdict) are set on first insert and not overwritten on same-day re-run
- [ ] Test verifies anchor is updated, verdict/metrics are from the first run
- [ ] Full test suite passes
