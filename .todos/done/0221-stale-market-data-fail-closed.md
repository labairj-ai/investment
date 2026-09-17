# Make Stale Market Data Fail Closed on New Order Authorization

- **ID:** 0221
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`_refresh_market_prices()` silently skips failed quote fetches (`if not quote: continue`), leaving stale `market_price`/`market_value` on positions. `_nav()` falls back to `qty × avg_cost` when `market_value` is None. Neither is a hard block on new order authorization. A 20% market crash is invisible to the risk engine if quotes fail, and new orders can be approved against stale/optimistic NAV.

## Proposed approach

1. Add `_check_portfolio_mark_freshness(account_id, conn, policy) -> tuple[bool, list[str]]`: query `position_snapshots.price_as_of`; return `(False, stale_symbols)` if any is NULL or older than `policy.halt_on_data_stale_minutes()`.
2. In `run_execution_cycle()`, after `_refresh_market_prices()`: call freshness check. If not fresh, log warning, skip `process_new_intents()` (no new authorizations), and return `{"market_state": "stale", "stale_symbols": [...], "new_intents_blocked": True, ...}`.
3. Add `RISK_STATE_STALE` as the first check in `risk_engine.evaluate()`: if any position mark is stale, return REJECTED without running the 19 rules.

## Touches

- `trade_engine/execution_engine.py` — `run_execution_cycle()`, new `_check_portfolio_mark_freshness()`
- `trade_engine/risk_engine.py` — `evaluate()` preamble, `_nav()`
- `tests/test_trade_engine.py` — stale-mark blocking tests

## Done when

- [ ] `_check_portfolio_mark_freshness()` returns stale symbols when `price_as_of` is NULL or old
- [ ] `run_execution_cycle()` skips new intents when any position mark is stale
- [ ] Return dict includes `market_state: stale` and `new_intents_blocked: True` when blocked
- [ ] `evaluate()` returns REJECTED with rule=RISK_STATE_STALE for stale portfolio state
- [ ] Stale block clears when quotes refresh successfully
- [ ] All existing tests pass
