# Improve Preference Learner: Recency-Weighted Threshold and More Dimensions

- **ID:** 0055
- **Status:** backlog
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

## Done when

- [ ] Sell threshold uses recency-weighted P25 (not min) when ≥ 5 accepted sell decisions exist
- [ ] `upside_preservation_bias` preference field computed and stored
- [ ] `valuation_tolerance` preference field computed and stored
- [ ] Learned preferences confirmed to have no path to overriding hard strategy rules
- [ ] Old `min()` threshold logic removed
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change
