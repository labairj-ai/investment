# Populate account_snapshots Every Execution Cycle

- **ID:** 0214
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0210

## Problem

`account_snapshots` table was designed as the historical account-state ledger for drawdown reconstruction, decision quality, strategy attribution, and risk debugging. It exists in the schema (agent_db.py:654) but nothing ever writes to it. The table also has a thin schema (only `cash, nav, buying_power, snapshot_at`) — it's missing the richer state needed for meaningful audit and reconciliation.

## Proposed approach

1. Expand `account_snapshots` schema via `_new_cols`:
   - `gross_exposure REAL` — sum of abs(market_value) across all positions
   - `reserved_cash REAL` — open buy notional (from todo 0211)
   - `open_order_notional REAL` — same as reserved_cash (all open orders)
   - `realized_pnl_today REAL` — today's `SUM(realized_pnl)` from fills
   - `unrealized_pnl REAL` — `SUM(market_value - qty*avg_cost)` from position_snapshots
   - `snapshot_reason TEXT` — e.g., "pre_cycle", "post_cycle"

2. Add `_write_account_snapshot(account_id: str, conn: sqlite3.Connection, reason: str = "cycle")` to `execution_engine.py`. Queries current state and INSERTs one row.

3. Call in `run_execution_cycle()` (after todo 0210 restructuring):
   - Before `process_new_intents()` → `reason="pre_cycle"`
   - After `process_open_orders()` → `reason="post_cycle"`

## Touches

- `agent_db.py` — `_new_cols` (6 new account_snapshots columns)
- `trade_engine/execution_engine.py` — `_write_account_snapshot()`, calls in `run_execution_cycle()`
- `tests/test_trade_engine.py` — verify snapshot rows written with correct values

## Done when

- [x] `account_snapshots` has all 6 new columns after migration
- [x] `run_execution_cycle()` writes a "pre_cycle" snapshot before processing new intents
- [x] `run_execution_cycle()` writes a "post_cycle" snapshot after open-order processing
- [x] Snapshot `nav` matches `cash + sum(market_value)` at time of write
- [x] Snapshot `realized_pnl_today` matches today's fill P&L
- [x] All 391 existing tests still pass

## Outcome

account_snapshots has gross_exposure, open_order_notional, realized_pnl_today, snapshot_type, cycle_id, position_count. run_execution_cycle() writes pre_cycle and post_cycle snapshots. Test section 16 verifies.
