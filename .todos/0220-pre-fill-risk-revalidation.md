# Add Pre-Fill Risk Revalidation Before Every Fill Retry

- **ID:** 0220
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`process_open_orders()` calls `broker.attempt_fill()` with no risk re-check. Between initial approval and fill retry, another trade may have exhausted daily notional, triggered a circuit breaker, or caused NAV to drop past the drawdown limit. An order approved under prior account state can fill in a state that would have rejected it. Subtlety: the order being retried is already counted in `_open_buy_notional()`, so a naïve re-call to `evaluate()` double-counts its own reservation and rejects valid orders.

## Proposed approach

1. Add `exclude_order_id: str | None = None` and `phase: str = "PRE_ORDER"` to `risk_engine.evaluate()`. Thread `exclude_order_id` into `_open_buy_notional()` and `_open_sell_qty()` as `AND order_id != ?` when set.
2. Add `phase TEXT` column to `risk_decisions` table via `_new_cols` in `agent_db.py`.
3. In `process_open_orders()`, before each `broker.attempt_fill()`: call `risk_evaluate(intent, policy, account, conn, exclude_order_id=order.order_id, phase="PRE_FILL")`. If REJECTED, cancel the order and sync intent status.
4. Both RiskDecision rows (PRE_ORDER + PRE_FILL) written to `risk_decisions`.

## Touches

- `trade_engine/risk_engine.py` — `evaluate()`, `_open_buy_notional()`, `_open_sell_qty()`
- `trade_engine/execution_engine.py` — `process_open_orders()`
- `agent_db.py` — `_new_cols`: `risk_decisions.phase`
- `tests/test_trade_engine.py` — self-exclusion test, pre-fill rejection test

## Done when

- [ ] `evaluate()` accepts `exclude_order_id` and `phase` parameters
- [ ] `_open_buy_notional()` and `_open_sell_qty()` exclude the specified order
- [ ] `risk_decisions` table has `phase` column
- [ ] `process_open_orders()` calls `risk_evaluate(..., phase="PRE_FILL")` before each fill
- [ ] WORKING order that would violate limits post-approval → CANCELLED, intent → EXPIRED
- [ ] Self-exclusion: order's own notional is not double-counted during pre-fill check
- [ ] Both PRE_ORDER and PRE_FILL decisions persist in `risk_decisions`
- [ ] All existing tests pass
