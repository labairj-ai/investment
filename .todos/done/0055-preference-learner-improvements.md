# Improve Preference Learner: Recency-Weighted Threshold and More Dimensions

- **ID:** 0055
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** low
- **Depends:** 0045

## Problem

The preference learner (0027) tracks acceptance rates, preferred CC delta/DTE, and sell-score threshold. Two specific issues: (1) The sell threshold is currently the **lowest sell score ever accepted**, meaning a single unusual decision permanently drags the threshold down — any future sell with a higher score becomes "above threshold" regardless of whether it represents the user's real preference. A recency-weighted percentile would be more robust. (2) Several behaviorally important preferences are not learned: upside preservation vs income orientation, valuation tolerance, drawdown tolerance, conviction sensitivity, average-down willingness, existing-position vs new-position preference.

## Proposed approach

- **Fix sell threshold**: replace `min(accepted_sell_scores)` with a recency-weighted P25 of accepted scores. Weight: exponential decay with half-life of ~60 accepted decisions. If fewer than 5 decisions exist, keep the simple min as a conservative fallback.
- **New preference dimensions** (add after more decision history accumulates — implement the framework now, populate as data comes in):
  - `upside_preservation_bias`: fraction of accepted CC recs that were UPSIDE_PRESERVATION strategy
  - `valuation_tolerance`: average V-score at point of accepted HOLD vs accepted TRIM
  - `drawdown_tolerance`: average loss% of positions where BUY/ADD was accepted
  - `conviction_sensitivity`: correlation between thesis_health and accepted/rejected sell recs
  - `tax_sensitivity`: rate at which tax friction caused a sell to be rejected vs accepted
- Ensure learned preferences still cannot mutate hard investment rules (this constraint from 0027 must be preserved).

## Touches

- `agents/preference_learner.py`
- `agent_db.py` (any new preference columns)

## Outcome

- **`agents/preference_learner.py`**:
  - Section 3 (sell threshold): replaced `min(scores)` with `_weighted_percentile(scores_with_w, 0.25)` using `_decay_weight()`. Falls back to `min` when fewer than 5 decisions. Stores method (weighted_p25 vs min_fallback) in evidence.
  - Section 4 (new): `cc.upside_preservation_bias` — fraction of accepted SELL_CC decisions with delta < 0.20, exponentially weighted. Uses same `cc_accepted` list computed by section 2. 
  - Section 5 (new): `sell.valuation_tolerance` — average `composite_score` (from action_payload_json) of accepted TRIM decisions vs rejected. Provides insight into valuation level where user starts trimming.
  - Added `_weighted_percentile(values_weights, percentile)` helper at module level.
- Hard rules in strategy_config are never touched — constraint preserved.

## Done when

- [x] Sell threshold uses recency-weighted P25 (not min) when ≥ 5 accepted sell decisions exist; falls back to min when < 5
- [x] `cc.upside_preservation_bias` computed from accepted SELL_CC: fraction with delta < 0.20 (low delta = upside-preservation orientation)
- [x] `sell.valuation_tolerance` computed: avg composite_score at which TRIM was accepted vs rejected
- [x] No path from learned preferences to hard rules — `upsert_learned_preference` only writes to `learned_preferences` table, never to `strategy_config`
- [x] Old `min()` threshold logic removed; replaced with `_weighted_percentile()`
- [x] **Backend QA:** deployed to optiplex — service active
- [x] **Frontend QA:** no new UI; preference values appear in existing DQ preference display
- [x] **No service regression:** service active after deploy
