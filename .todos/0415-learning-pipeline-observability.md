# Surface Learning Pipeline Failures Instead of Swallowing Them

- **ID:** 0415
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0411

## Problem

The shadow-observation block in `score_for_observe()` is wrapped in a bare `except Exception: pass`, so any failure — including the `_q`/`q_score` mismatch that causes `predict_alpha()` to return None — disappears silently. With prospective observations now driving model promotion and degradation decisions, a silent failure is dangerous: the learner stops accumulating evidence while everything appears healthy. There is no `last_successful_shadow_score` timestamp visible in readiness reports.

## Proposed approach

- Replace the silent `except Exception: pass` in `score_for_observe()` with structured error logging: log at ERROR level, write a `learning_pipeline_failure` event to a new `learning_health_events` table (or the existing notification/event table), and re-raise or surface as a non-fatal return value.
- The recommendation flow must still survive — base OH recommendations must not fail because of a learning error — but the failure must be recorded.
- Expose `last_successful_shadow_score_at`, `last_shadow_model_version`, `last_shadow_cohort_id` in `learning_readiness_report()`.
- Add a `learning_pipeline_health` key to `compute_data_health()` that returns BLOCK when no successful shadow score has been recorded in the last N days (e.g. 3 trading days for an active PAPER_ACTIVE model).
- Add a test that injects a scoring failure (e.g. corrupt model weights) and asserts the failure event is written and health degrades to BLOCK.

## Touches

- `agents/learning/challenger.py` — `score_for_observe()` error handling
- `agents/learning/calibration.py` — `learning_readiness_report()`, `compute_data_health()`
- `agent_db.py` — possible new event/health table or column
- `tests/test_calibration.py`

## Done when

- [ ] A scoring exception in `score_for_observe()` is logged at ERROR and written to a persistent event record
- [ ] Base OH recommendations are unaffected by a learning failure
- [ ] `learning_readiness_report()` includes `last_successful_shadow_score_at` and `last_shadow_cohort_id`
- [ ] `compute_data_health()` returns BLOCK when no successful shadow score exists for an active PAPER_ACTIVE model in the past 3 trading days
- [ ] Test confirms failure event written and health degrades
