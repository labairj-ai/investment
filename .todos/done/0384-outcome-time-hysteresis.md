# Anchor Degradation Hysteresis on Outcome Label Time

- **ID:** 0384
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0377, 0378

## Problem

The 0377 hysteresis implementation anchors on `last_snapshot_max_obs_id` and counts new evidence as observations where `id > anchor`. This is semantically wrong: observation IDs reflect when a candidate was scored, not when its outcome matured. An observation created early but labeled late (due to a missing price, failed labeling job, or late data ingestion) will have a low ID and be excluded from "new evidence" even though it genuinely became available after the previous snapshot. The check also uses a raw row count rather than requiring that the new evidence spans independent market decision dates, so 15 observations from a single volatile day count the same as 15 observations from 15 different days.

## Proposed approach

- Replace `last_snapshot_max_obs_id` in `model_performance_snapshots` with `last_outcome_labeled_at TEXT` (ISO timestamp of the latest `outcome_labeled_at` value in the evaluation window).
- In `_check_degradation()`, count new evidence as rows where `outcome_labeled_at > previous_snapshot_cutoff` — semantically "outcomes that became available since the last snapshot."
- Additionally require that new evidence spans at least `DEGRADATION_MIN_NEW_COHORT_DAYS` distinct `scored_at_date` values (independent market decision dates), not just a raw row count. This prevents a burst of late-maturing outcomes from a single cohort from triggering a snapshot prematurely.
- Migrate existing snapshots: rows with `last_snapshot_max_obs_id` set but no `last_outcome_labeled_at` should fall back to the ID-based check for backward compat (or simply proceed without hysteresis for legacy snapshots).
- Also fix the timezone issue in `score_for_observe()`: compute `scored_at_date` in `America/New_York` rather than UTC so that evening runs don't advance to the next calendar date.

## Touches

- `agent_db.py` — `_new_cols`: `last_outcome_labeled_at TEXT` on `model_performance_snapshots`
- `agents/learning/calibration.py` — `_check_degradation()`: hysteresis anchor and new-evidence count
- `agents/learning/challenger.py` — `score_for_observe()`: `scored_at_date` timezone fix
- `tests/test_calibration.py` — test late-maturing observation counts as new evidence; test single-day burst does not trigger snapshot

## Done when

- [ ] `model_performance_snapshots` stores `last_outcome_labeled_at`
- [ ] New evidence counted by `outcome_labeled_at > previous_cutoff`, not by observation ID
- [ ] Snapshot skipped unless new evidence spans `>= DEGRADATION_MIN_NEW_COHORT_DAYS` distinct `scored_at_date` values
- [ ] A late-labeled observation (old ID, recent `outcome_labeled_at`) counts as new evidence after the cutoff
- [ ] `scored_at_date` in `score_for_observe()` uses America/New_York date
- [ ] `python -m pytest tests/` passes with no regressions
