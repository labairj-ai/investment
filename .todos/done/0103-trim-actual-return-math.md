# Correct Executed-TRIM Actual-Return Math and Split Action Branches

- **ID:** 0103
- **Status:** done
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** none

## Problem

`outcome_evaluator.py` computes `actual_r` for an accepted+executed TRIM as `(1 - f) * hold_r`, which ignores the return earned on the sold fraction between the recommendation date and the actual execution date. The correct formula for a trim-to-cash is `actual_r = (1-f)*hold_r + f*((exec_price/entry_price)-1)`; if proceeds are reinvested, the replacement leg return must start from `exec_date`, not from the recommendation date. ALLOCATE and REBALANCE share the same generic executed-non-EXIT branch and have no dedicated accounting. The lifecycle test (`test_lifecycle.py`) currently asserts `expected_actual = (1-0.25)*hold_r`, cementing the wrong formula — the test suite is protecting the bug.

## Proposed approach

- Add `_compute_actual_trim(exec_rec, entry_price, hold_r, prices)` helper: sold fraction earns `(exec_price/entry_price) - 1`; remaining fraction earns `hold_r`; if `replacement_ticker` present in rec metadata, the replacement leg return is computed from `exec_date` forward.
- Add `_compute_actual_allocate(exec_rec, entry_price, prices)` helper: return on newly purchased shares from `exec_price` to horizon price.
- Add `_compute_actual_rebalance(rec, exec_rec, entry_price, prices)` helper: blended from-ticker + to-ticker return, using respective exec prices and dates.
- Route `_compute_returns()` to the correct helper by action type; remove the generic executed-non-EXIT fallback that now covers TRIM/ALLOCATE/REBALANCE.
- Fix the lifecycle test to assert the correct TRIM formula.
- In `decision_quality.py`, gate TRIM/ALLOCATE/REBALANCE out of the learning set until at least N (e.g. 5) correctly-computed outcomes exist — add a `_EXCLUDE_FROM_DQ` set and filter in `compute_agent_edge()`.

## Touches

- `agents/outcome_evaluator.py` — `_compute_returns()`, new `_compute_actual_*()` helpers
- `agents/decision_quality.py` — `compute_agent_edge()` exclusion gate
- `tests/test_lifecycle.py` — fix asserted TRIM actual_r value
- `tests/test_outcome_evaluator.py` (if it exists) or `tests/test_agent_db.py` — add unit tests for each new helper

## Done when

- [ ] `_compute_actual_trim()` exists and returns the correct two-component formula (cash leg + hold leg); verified with a unit test against a known set of prices.
- [ ] When `replacement_ticker` is present, the reinvestment leg return starts from `exec_date`, confirmed by a test where rec_date price ≠ exec_date price for the replacement.
- [ ] `_compute_actual_allocate()` and `_compute_actual_rebalance()` exist with dedicated unit tests.
- [ ] The old generic executed-non-EXIT branch no longer handles TRIM/ALLOCATE/REBALANCE.
- [ ] Lifecycle test `test_trim_actual_return` (or equivalent) asserts `(1-f)*hold_r + f*(exec_gain)` and passes.
- [ ] `compute_agent_edge()` excludes TRIM/ALLOCATE/REBALANCE until threshold met; confirmed by a test that seeds outcomes and checks the exclusion gate.
- [ ] Full pytest suite (149+ tests) passes with no regressions.
- [ ] Manually verify on optiplex DB: re-running the evaluator on any existing TRIM outcome row produces a different (corrected) `actual_return` value compared to the old formula (document expected vs. actual in PR description).
