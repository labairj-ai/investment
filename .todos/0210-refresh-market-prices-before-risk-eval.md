# Refresh Market Prices Before Risk Evaluation in run_execution_cycle

- **ID:** 0210
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`run_execution_cycle()` (execution_engine.py:317) calls `process_new_intents()` before `process_open_orders()`. Market-price refresh happens at the top of `process_open_orders()`. This means new intents are risk-evaluated against the previous cycle's position marks — potentially stale by hours. If ANET rises from $140 to $170 overnight, a new BUY intent is risk-authorized using the $140 NAV, understating concentration risk. The invariant "no TradeIntent is risk-authorized against stale portfolio state" must be enforced structurally, not hoped for.

## Proposed approach

Restructure `run_execution_cycle()`:
```
1. _refresh_market_prices(account_id, conn)       # fresh MtM prices — always first
2. _update_nav_high_water(account_id, conn)        # peak NAV using fresh prices
3. _write_account_snapshot(account_id, conn, "pre") # pre-cycle state snapshot
4. process_new_intents(account_id, conn)           # risk on fresh state
5. process_open_orders(account_id, conn)           # retry fills (no re-refresh)
6. _write_account_snapshot(account_id, conn, "post") # post-fill state snapshot
```

Remove the `_refresh_market_prices` and `_update_nav_high_water` calls from inside `process_open_orders()` to avoid double refresh. `process_open_orders()` should just retry fills using prices that were already refreshed at cycle start.

Add `_write_account_snapshot()` stub (actual implementation is todo 0214; this todo only restructures the cycle order and adds the call sites).

## Touches

- `trade_engine/execution_engine.py` — `run_execution_cycle()`, `process_open_orders()`
- `tests/test_trade_engine.py` — add tests verifying refresh precedes risk eval

## Done when

- [ ] `run_execution_cycle()` refreshes MtM prices before calling `process_new_intents()`
- [ ] `process_open_orders()` no longer calls `_refresh_market_prices()` or `_update_nav_high_water()` internally
- [ ] Test: risk engine sees updated `market_value` on position_snapshots when evaluating a new intent
- [ ] Test: `nav_high_water` is updated before the first intent in a cycle is evaluated
- [ ] All 391 existing tests still pass
