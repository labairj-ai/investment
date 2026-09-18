# Align Degradation Monitor Baseline and Add Incremental Edge Signal

- **ID:** 0383
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0375, 0377, 0378

## Problem

Promotion and degradation use different baselines, creating an inconsistent standard for the same model. `compute_prospective_metrics()` (promotion) correctly uses per-row `baseline_predicted_alpha` captured at prediction time — an ex-ante baseline. `_check_degradation()` (suspension) computes `baseline_mae` against the hindsight mean of current outcomes, which is a look-ahead baseline the model never had access to. Beyond the baseline mismatch, degradation asks only whether the challenger has positive absolute ranking power, not whether it still improves on the unchanged base strategy. A model that retains positive absolute ranking spread but has drifted to `incremental_ranking_spread < 0` (challenger now worse than base) will not be flagged, even though learning has become actively harmful.

## Proposed approach

- **Fix degradation baseline**: replace the hindsight `baseline_mae` in `_check_degradation()` with `mean(|baseline_predicted_alpha - outcome|)` using per-row `baseline_predicted_alpha` from `model_observations` — the same contract as `compute_prospective_metrics()`.
- **Add incremental spread to degradation snapshots**: compute `rolling_base_ranking_spread`, `rolling_challenger_ranking_spread`, and `rolling_incremental_spread` over the degradation window and store them in `model_performance_snapshots`.
- **New degradation signal**: treat two consecutive non-overlapping snapshots with `rolling_incremental_spread < 0` as a degradation trigger alongside the existing ranking/MAE signals. A model that's become worse than the base strategy should be suspended even if it retains positive absolute ranking.
- Align the degradation window size and hysteresis rules (from 0377) with the promotion observation requirements so the two subsystems are measuring comparable populations.

## Touches

- `agents/learning/calibration.py` — `_check_degradation()`, `model_performance_snapshots` insert
- `agent_db.py` — `_new_cols`: `rolling_base_ranking_spread REAL`, `rolling_challenger_ranking_spread REAL`, `rolling_incremental_spread REAL` on `model_performance_snapshots`
- `tests/test_calibration.py` — test that ex-ante baseline is used; test that negative incremental spread triggers suspension

## Done when

- [ ] `_check_degradation()` uses per-row `baseline_predicted_alpha` for `baseline_mae`, not hindsight mean
- [ ] `model_performance_snapshots` stores `rolling_base_ranking_spread`, `rolling_challenger_ranking_spread`, `rolling_incremental_spread`
- [ ] Two consecutive non-overlapping snapshots with `rolling_incremental_spread < 0` trigger suspension
- [ ] A model with positive absolute ranking but negative incremental spread is correctly suspended
- [ ] `python -m pytest tests/` passes with no regressions
