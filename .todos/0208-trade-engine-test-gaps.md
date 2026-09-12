# Trade Engine Test Gaps: Rules 14-18 and Safety Edge Cases

- **ID:** 0208
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0199, 0200, 0201, 0202, 0203

## Problem

The existing `TestRiskEngine` class claims "one test per rule" but stops at rule 13 (NO_NAKED_OPTIONS) and then jumps to the all-pass test. Rules 14-18 have no dedicated tests. These are among the most important safety controls:

- 14 MAX_CONTRACTS_PER_SYMBOL
- 15 DATA_FRESHNESS
- 16 NO_EARNINGS_CONFLICT
- 17 MAX_DAILY_LOSS
- 18 MAX_DRAWDOWN

Additionally, several behavioral safety properties introduced in 0199-0206 need regression coverage.

## Proposed approach

**Add to `TestRiskEngine` in `tests/test_trade_engine.py`:**

- `test_max_contracts_per_symbol_rejects` — open=1 contract, limit=1 → FAIL; also test the off-by-one fix (requesting 2 with limit=1, open=0 → FAIL)
- `test_data_freshness_stale_option_quote_rejects` — insert option_quote_snapshot with `captured_at` > stale_minutes ago → FAIL
- `test_no_earnings_conflict_rejects` — insert event_calendar earnings between today and expiration → FAIL
- `test_max_daily_loss_rejects` — insert fills with negative `realized_pnl` summing to > limit → FAIL (requires 0202)
- `test_max_drawdown_rejects` — set `nav_high_water` high, drop current NAV below threshold → FAIL (requires 0201)

**Add to `TestShadowBroker` / new `TestExecutionSafety`:**

- `test_no_fill_when_quote_unavailable` — mock `_get_quote` → None; assert no fill row, order remains WORKING (requires 0200)
- `test_no_fill_on_saturday` — mock now() to Saturday; assert attempt_fill returns None (requires 0203)
- `test_no_fill_on_nyse_holiday` — mock now() to Christmas Day; assert no fill
- `test_working_order_retried_on_next_cycle` — cycle 1: quote doesn't cross limit → WORKING; cycle 2: quote crosses limit → FILLED (requires 0199)
- `test_day_order_expires_after_market_close` — mock now() to 4:30 PM ET; attempt_fill → EXPIRED (requires 0203)
- `test_full_exit_at_loss_daily_loss_circuit_fires` — buy 10 @ $100, sell all 10 @ $70; next BUY intent → MAX_DAILY_LOSS FAIL (requires 0202)
- `test_concentration_uses_market_value` — buy 5 @ $100; price rises to $200 (update market_value); next large BUY → MAX_POSITION_WEIGHT FAIL at market value (requires 0201)
- `test_two_contract_intent_limit_one_rejects` — option intent with contracts=2, policy limit=1 → MAX_CONTRACTS_PER_SYMBOL FAIL (requires 0205)
- `test_concurrent_order_creation_one_row` — call `submit_order()` twice for same intent → exactly one orders row (requires 0206)

## Touches

- `tests/test_trade_engine.py` — ~15 new test methods

## Done when

- [ ] Rules 14-18 each have a dedicated failing-case test
- [ ] No-quote → no-fill test passes
- [ ] Saturday/holiday → no-fill tests pass
- [ ] WORKING order retry test passes
- [ ] Full-EXIT-at-loss → daily-loss circuit test passes
- [ ] Market-value concentration test passes
- [ ] Two-contract limit-one rejection test passes
- [ ] All new tests run with no live network calls (all yfinance/clock mocked)
