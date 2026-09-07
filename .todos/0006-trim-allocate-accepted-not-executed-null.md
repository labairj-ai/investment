# TRIM/ALLOCATE Accepted-Not-Executed Outcome Should Be NULL

- **ID:** 0006
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0001

## Problem

When a TRIM or ALLOCATE recommendation is accepted but no execution record is ever created, `_compute_scenarios()` in `outcome_evaluator.py` falls through to `actual_r = hold_r, actual_is_estimated = True`. Using `hold_r` as the estimated return for an accepted TRIM is defensible (assuming they held), but it is indistinguishable in the DB from a genuine hold outcome. The decision-quality model can therefore mislearn: it may credit the user with a correct "hold" decision when they actually accepted a trim and never executed it — or penalize them for a bad trim return they never took.

## Proposed approach

- In `_compute_scenarios()`, extend the `accepted + no exec_rec` branch to cover TRIM, ALLOCATE, and REBALANCE, not just EXIT_ACTIONS:
  ```python
  elif decision == "accepted" and action in {*EXIT_ACTIONS, "TRIM", "ALLOCATE", "REBALANCE"}:
      actual_r = None
      actual_is_estimated = True
  ```
- Add an explicit `outcome_reason` enum value `ACCEPTED_NOT_EXECUTED` that can be stored in the outcome row so reports can distinguish this state from a genuine "no execution data available" case
- Decision-quality model should skip rows where `actual_r IS NULL` — verify this guard exists in `decision_quality.py`

## Touches

- `agents/outcome_evaluator.py`
- `agents/decision_quality.py`
- `agent_db.py` (consider adding `outcome_reason` column to `recommendation_outcomes`)
- `tests/test_outcome_evaluator.py`

## Done when

- [ ] Accepted TRIM with no execution record produces `actual_return = NULL` and `actual_is_estimated = 1` in `recommendation_outcomes`
- [ ] Accepted ALLOCATE with no execution record produces the same
- [ ] `decision_quality.py` skips `actual_return IS NULL` rows when computing agent alpha
- [ ] Unit test: accepted TRIM + no exec → `actual_r = None`
- [ ] Unit test: accepted TRIM + exec record present → `actual_r` is computed from execution fraction
- [ ] Existing outcome evaluator tests still pass (regression)
