# Fix Accepted EXIT Without Execution to Not Claim 0% Return

- **ID:** 0071
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** 0070

## Problem

In `_compute_scenarios()`, the branch `elif decision == "accepted" and action in EXIT_ACTIONS` sets `actual_r = 0.0` and `actual_is_estimated = False`. This means accepting an EXIT recommendation — without ever selling — permanently records a confirmed 0% return in `recommendation_outcomes`. The Decision Quality model will then treat non-executed accepts as real outcomes, potentially learning from trades that never happened.

## Proposed approach

- Introduce a distinction between "accepted with execution" and "accepted without execution."
- If `decision == "accepted"` and `action in EXIT_ACTIONS` **and** no `exec_rec` exists, set `actual_r = None` and `actual_is_estimated = True` (or use a new state constant like `"accepted_pending"` in `actual_return_method` if that column is added).
- Only set `actual_r = 0.0, actual_is_estimated = False` when there is a real execution record confirming the sale.
- Consider adding a `notes` field to `recommendation_outcomes` that records the actual disposition (e.g., `"accepted_no_execution"`) to allow future filtering.
- Update Decision Quality to explicitly exclude rows where `actual_is_estimated = True` when computing user override alpha.

## Touches

- `agents/outcome_evaluator.py` — `_compute_scenarios()` EXIT branch
- `agents/decision_quality.py` — filter logic for which rows are trustworthy
- `tests/test_outcome_evaluator.py` — update `test_accepted_exit_actual_zero` to reflect new behavior

## Done when

- [ ] Accepted EXIT with no execution record produces `actual_r = None, actual_is_estimated = True`
- [ ] Accepted EXIT with an execution record produces `actual_r` from execution price, `actual_is_estimated = False`
- [ ] Decision Quality model only uses rows where `actual_is_estimated = False`
- [ ] Existing test updated; new test covers accepted EXIT with execution record
