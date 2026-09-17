# Promotion Governance V2

- **ID:** 0348
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0342

## Problem

Two loopholes remain in the promotion governance added in 0342:

1. **`promotion_metrics_snapshot` contains gate booleans, not the underlying metric values.** The stored JSON is `{"unique_tickers": True, "unique_weeks": True, ...}` — the gate pass/fail flags. A future audit needs to reconstruct *why* the model qualified: what were the actual values and what were the thresholds at promotion time? Without the raw values, you cannot know whether `unique_tickers=True` meant 10 tickers (barely passing) or 200.

2. **`force=True` can bypass all gates for any transition, not just retirement.** The docstring says "use for RETIRED" but the code allows `force=True` to send any model from any state to any allowed target without gate checks. This means a model can be promoted to PAPER_ACTIVE with no statistical validation if the caller passes `force=True`, and the log row provides no indication that gates were skipped.

## Proposed approach

**Complete metrics snapshot:**
Store a richer JSON in `promotion_metrics_snapshot`:
```json
{
  "unique_tickers":        {"value": 42, "minimum": 10, "pass": true},
  "unique_decision_dates": {"value": 38, "minimum": 30, "pass": true},
  "unique_weeks":          {"value": 14, "minimum": 4,  "pass": true},
  "cv_folds":              {"value": 3,  "minimum": 1,  "pass": true},
  "beats_baseline":        {"value": true, "pass": true},
  "cv_mae_mean":           {"value": 0.031},
  "baseline_mae_mean":     {"value": 0.039},
  "ranking_spread_ci_low": {"value": 0.009},
  "ranking_spread_ci_high":{"value": 0.041},
  "gates_bypassed":        false
}
```
Pull the actual `validation_metrics` values from the `learning_models` row at promotion time and populate the snapshot.

**Restrict `force=True`:**
- Allow `force=True` only for `→ RETIRED` transitions; raise `ValueError` if `force=True` and `target_state != RETIRED`
- For cases where a legitimate override of non-retirement promotion is needed, require an explicit `override_reason: str` parameter (non-optional, non-empty); store `"gates_bypassed": true` and the override reason in the snapshot
- The log row must be auditable: any snapshot with `gates_bypassed: true` should be visually flagged in the dashboard

**Optional but recommended:** bump `MIN_CV_FOLDS_FOR_OBSERVE` from 1 to at least 2 to prevent promotion on a single fold.

## Touches

- `agents/learning/calibration.py` — `_check_promotion_gates()`: return actual metric values alongside pass/fail; `promote()`: build rich snapshot from model row + gate result values; restrict `force=True` to RETIRED; add `override_reason` param
- `agent_db.py` — no schema change needed if snapshot is JSON; optionally add `gates_bypassed BOOLEAN` column for indexed queries
- `serve.py` or admin endpoint — flag `gates_bypassed: true` snapshots differently
- `tests/test_calibration.py` — assert snapshot contains numeric values (not just booleans); assert `force=True` on non-RETIRED raises or is rejected; assert `override_reason` is stored when override used

## Done when

- [x] `promotion_metrics_snapshot` contains actual metric values, thresholds, and pass/fail for each gate
- [x] `force=True` on a non-RETIRED transition raises `ValueError` (or is blocked with a clear error)
- [x] Override promotions (if ever needed) require non-empty `override_reason` and store `gates_bypassed: true` in the snapshot
- [x] A future audit on `model_promotion_log` can answer: what were the exact metric values when this model was promoted?
- [x] `python -m pytest tests/` passes with no regressions

## Outcome

`_check_promotion_gates()` returns rich dict with `{value, minimum/expected, pass}` per gate. `promote()` builds detailed snapshot from gate results + validation_metrics; `force=True` restricted to RETIRED (raises ValueError otherwise); `override_reason` param bypasses gates with `gates_bypassed=True` stored. Pre-existing tests using `force=True` on non-RETIRED updated to use `override_reason="test"`. `TestPromotionGovernanceV2_0348` adds 4 tests. 847 tests pass.
