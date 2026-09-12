# Fix Partial Fill Quantity: Use Remaining Qty, Not Original Order Qty

- **ID:** 0224
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`attempt_fill()` in `shadow_broker.py` uses `qty = order.quantity or 0.0` — the original order quantity — ignoring `order.fill_qty` (already filled). This means every fill attempt re-fills the full original size, inflating cash debits and position sizes. `_apply_fill()` always transitions to FILLED rather than PARTIALLY_FILLED, so partial fills never reach a stable intermediate state.

## Proposed approach

1. `attempt_fill()`: compute `remaining = (order.quantity or 0.0) - (order.fill_qty or 0.0)`. Guard: `if remaining <= 0: return None`. Use `remaining` as the fill quantity.
2. `_apply_fill()`: after updating `new_fill_qty`, if `new_fill_qty < order.quantity` → transition to PARTIALLY_FILLED; if `new_fill_qty >= order.quantity` → transition to FILLED.
3. `_open_buy_notional()` already uses `quantity - fill_qty` but verify it handles PARTIALLY_FILLED correctly.

## Touches

- `trade_engine/shadow_broker.py` — `attempt_fill()`, `_apply_fill()`
- `tests/test_trade_engine.py` — partial fill lifecycle tests, reservation accounting

## Done when

- [ ] `attempt_fill()` fills only remaining quantity (`order.quantity - order.fill_qty`)
- [ ] `attempt_fill()` returns None when `fill_qty >= quantity` (fully filled guard)
- [ ] `_apply_fill()` transitions to PARTIALLY_FILLED when `new_fill_qty < order.quantity`
- [ ] `_apply_fill()` transitions to FILLED when `new_fill_qty >= order.quantity`
- [ ] Two-fill test: 60/100 shares → PARTIALLY_FILLED; then 40 → FILLED; two fills in DB; total cash = 100 × price
- [ ] `_open_buy_notional()` correctly reflects remaining (unfilled) quantity for partial orders
- [ ] All existing tests pass
