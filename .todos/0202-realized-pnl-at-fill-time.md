# Capture Realized P&L at Fill Time for Reliable Circuit Breakers

- **ID:** 0202
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`MAX_DAILY_LOSS` in the risk engine joins today's sell fills back to `position_snapshots.avg_cost`. But `ShadowBroker._apply_fill()` deletes the position row when `qty` reaches zero (full EXIT). After a complete exit at a loss, the position row is gone — the daily-loss check sees `avg_cost = NULL` and misses the loss entirely.

The circuit breaker that should halt trading after a bad day is unreliable.

## Proposed approach

**Capture cost basis and realized P&L at fill time** — before any position mutation.

Add columns to `fills`:
```sql
cost_basis      REAL   -- avg_cost × qty at time of fill (for sell fills)
realized_pnl    REAL   -- proceeds - cost_basis (negative = loss)
realized_pnl_pct REAL  -- realized_pnl / cost_basis * 100
```

In `ShadowBroker._apply_fill()`, before updating `position_snapshots`:
```python
if is_sell:
    avg_cost = existing_pos["avg_cost"] if existing_pos else 0.0
    cost_basis = fill.qty * avg_cost
    proceeds = fill.qty * fill.price - fill.fee
    realized_pnl = proceeds - cost_basis
    realized_pnl_pct = (realized_pnl / cost_basis * 100) if cost_basis else 0.0
    # Write these into fills row
```

**Update `MAX_DAILY_LOSS` rule**:
```python
row = conn.execute(
    "SELECT SUM(realized_pnl) as loss FROM fills WHERE account_id=? AND DATE(filled_at)=? AND realized_pnl < 0",
    (account_id, today)
).fetchone()
daily_loss = abs(float(row["loss"] or 0))
```

This is now authoritative regardless of whether positions still exist.

**Future**: separate `MAX_REALIZED_DAILY_LOSS` (from fills) and `MAX_NAV_DAILY_LOSS` (from account_snapshots mark-to-market) as distinct circuit breakers.

## Touches

- `fills` table — add `cost_basis`, `realized_pnl`, `realized_pnl_pct` columns
- `trade_engine/shadow_broker.py` — capture at fill time in `_apply_fill()`
- `trade_engine/risk_engine.py` — update `MAX_DAILY_LOSS` to query `fills.realized_pnl`
- `agent_db.py` — add columns via `_new_cols` pattern

## Done when

- [ ] `fills` table has `cost_basis`, `realized_pnl`, `realized_pnl_pct`
- [ ] `_apply_fill()` writes these for SELL/BUY_TO_CLOSE fills before position update
- [ ] `MAX_DAILY_LOSS` queries `SUM(realized_pnl)` from fills, not position_snapshots join
- [ ] Test: buy 10 @ $100, sell all 10 @ $70 → position row deleted → daily_loss rule still sees $300 loss → rejects next trade
- [ ] Test: partial sell → realized_pnl correct for partial qty
