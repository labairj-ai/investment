# Rebuild CC Management Evaluator Around True MTM NAV Denominator

- **ID:** 0125
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** none

## Problem

All four CC management outcome paths (HOLD_CALL, BUY_TO_CLOSE, ROLL_*, ALLOW_ASSIGNMENT) normalize returns using `entry_price` — the stock price at the original SELL_CC recommendation date. This is economically wrong. By the time a management recommendation is made, the investor holds a covered position worth `S_rec − C_rec` (current stock price minus the mark of the short call at the CC management rec date). Using the wrong denominator makes the numerator and denominator refer to different points in time, producing inflated or deflated return figures that are not comparable across management actions.

The correct common baseline for all paths is `net_NAV = S_rec − C_rec`, where `S_rec` is the stock price at the CC management rec date and `C_rec` is the mid-price of the short call at that same date. This is the actual dollar value the investor would receive by immediately BTC-ing the call and selling the shares.

## Proposed approach

- In `_compute_cc_management_returns()`, accept a `net_nav: float` parameter (defaulting to `entry_price` until all callers pass it) and replace every `/ entry_price` denominator with `/ net_nav`.
- In `_compute_scenarios()`, fetch `C_rec` from `option_quote_snapshots` using the `option_snapshot_id` stored on the CC management recommendation (or its parent SELL_CC rec via `parent_recommendation_id`). Compute `net_nav = S_rec − C_rec` and pass it through.
- If `C_rec` is unavailable (older recs without a snapshot), fall back to `entry_price` so existing data isn't broken, and log a warning.
- Update all tests in `test_outcome_evaluator.py` to pass a realistic `net_nav` and verify correct division.

## Touches

- `agents/outcome_evaluator.py` — `_compute_cc_management_returns()`, `_compute_scenarios()`
- `agent_db.py` — may need a helper to fetch `mid_price` from `option_quote_snapshots`
- `tests/test_outcome_evaluator.py`

## Done when

- [ ] `_compute_cc_management_returns()` uses `net_nav` (not `entry_price`) as denominator for all management paths
- [ ] `_compute_scenarios()` fetches `C_rec` from `option_quote_snapshots` and computes `net_nav = S_rec − C_rec`
- [ ] Fallback to `entry_price` when snapshot unavailable, with a log warning
- [ ] All existing outcome evaluator tests pass using the new denominator
- [ ] At least one new test verifies a concrete BTC example: `net_nav = 170.00`, `btc_exec = 1.50` → `actual_r = (170 − 1.50 − 170) / 170 = −0.00882...` (just the closed premium)
