# Add Five Missing Lifecycle Tests From Reviewer Checklist

- **ID:** 0124
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0114

## Problem

The reviewer's specific test checklist included eight items. Three are done (accept→mature→outcome for HOLD/EXIT, accepted-unexecuted EXIT stays unknown, individual TRIM math unit tests). Five are genuinely missing:

1. **Two-fill TRIM uses VWAP + correct partial-sale return end-to-end**: Unit tests exist for `_compute_actual_trim`, but no lifecycle test exercises the full path: seed two executed_actions rows for the same rec → `aggregate_executions()` → `evaluate_matured_recommendations()` → verify the outcome row uses the VWAP exec_price and the two-component formula.

2. **SELL_CC execute → cc_positions row created atomically**: No test verifies that calling `record_execution_transaction()` for a SELL_CC both inserts into `executed_actions` AND creates an open row in `cc_positions` in a single transaction. The test should also verify that a simulated failure (e.g. deliberate integrity violation on cc_positions) rolls back the executed_actions insert.

3. **Roll leg-2 failure rolls back leg-1**: A ROLL execution writes two executed_actions rows. If the second INSERT fails (e.g. duplicate fill_id on leg 2), leg 1 must also be rolled back. No test covers this rollback path.

4. **CC management recommendation evaluated at maturity**: No lifecycle test seeds a BUY_TO_CLOSE or ROLL recommendation, ages it past the horizon, and runs `evaluate_matured_recommendations()` to verify a `recommendation_outcomes` row is written with the correct horizon and formula values.

5. **Financial fetch works from a freshly-created DB**: No test verifies that `financials_fetcher.compute_valuation_metrics(ticker)` works correctly when `company_financials` and `historical_valuation_metrics` tables are brand new (no prior rows). This catches migration omissions like the earlier `shares_period_end` regression where the column existed in the fetcher's INSERT but not in the CREATE TABLE.

## Proposed approach

All five tests should use the `mem_db` fixture so they run against a freshly migrated in-memory DB. Add to `tests/test_lifecycle.py` (tests 1-4) and `tests/test_financials.py` (test 5, new file or existing `test_agent_db.py`).

For test 3 (roll rollback), inject a failure by inserting a duplicate fill_id before the second leg, then assert `executed_actions` has zero new rows and `cc_positions` is unchanged.

For test 5, mock the yfinance calls to return controlled data, run `compute_valuation_metrics`, and assert the resulting rows in `historical_valuation_metrics` have the expected values.

## Touches

- `tests/test_lifecycle.py` — tests 1, 2, 3, 4
- `tests/test_agent_db.py` or new `tests/test_financials.py` — test 5
- `agent_db.py` may need a test-injectable failure path for rollback test

## Done when

- [ ] Test: two-fill TRIM lifecycle writes outcome with VWAP exec_price and correct actual_r
- [ ] Test: SELL_CC execute creates executed_action + cc_position row; partial failure rolls back both
- [ ] Test: ROLL leg-2 failure rolls back leg-1 executed_action
- [ ] Test: CC management (BUY_TO_CLOSE or ROLL) rec evaluated at maturity writes outcome row
- [ ] Test: `compute_valuation_metrics` on a fresh in-memory DB with no prior rows succeeds
