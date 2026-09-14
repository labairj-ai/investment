# Validate Fill Identity and Economics Before Booking

- **ID:** 0286
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0283

## Problem

`apply_broker_fill()` guards against duplicate fills, overfills, and impossible sells, but it trusts the broker adapter's field values without cross-checking them against the local order record. A mistranslated adapter could supply the wrong symbol, wrong side, a zero or negative quantity, or a fill for the wrong account — and the function would silently book it, mutating cash and position for an unrelated symbol or account. There is also no explicit rejection of zero, negative, or non-finite numeric fields, which allows IEEE edge cases (NaN, Inf) to corrupt financial state silently.

## Proposed approach

Before any DB write in `apply_broker_fill()`, validate the following against the resolved local order row:
- `fill.account_id` matches the `account_id` argument (execution account)
- `fill.symbol` matches `order.symbol`
- `fill.side` matches `order.side`
- `fill.qty > 0` and is finite (rejects zero, negative, NaN, Inf)
- `fill.price > 0` and is finite
- `fill.fee >= 0` and is finite
- `fill.broker_fill_id` is non-empty
- `fill.broker_order_id` matches the resolved order's `broker_order_id` (only when order has a real broker_order_id set; skipped for client_order_id crash-recovery path)

On any validation failure: raise a new `BrokerFillInvalid` exception (or equivalent) that quarantines the fill and halts new submissions — never silently update the wrong position. Add unit tests covering each validation path: each invalid field individually triggers the guard and leaves DB state unchanged.

## Touches

- `trade_engine/execution_engine.py` — `apply_broker_fill()`; new `BrokerFillInvalid` exception
- `tests/test_trade_engine.py` or `tests/test_chaos.py` — one test per invariant violation

## Done when

- [x] `apply_broker_fill()` validates account, symbol, side, qty, price, fee, broker_fill_id, and broker_order_id against the resolved order before any DB write
- [x] Zero, negative, and non-finite (NaN, Inf) qty/price/fee are rejected
- [x] A `BrokerFillInvalid` exception (or equivalent) is raised on any failure; DB state is unchanged after the raise
- [x] One test per invariant confirms the guard fires and no fill row is written
- [x] All existing 589 tests still pass

## Outcome

New `BrokerFillInvalid` exception added. `apply_broker_fill()` now fetches order row before INSERT OR IGNORE for validation (reused for mutations, eliminating the duplicate post-INSERT fetch). broker_order_id validation skipped when order.broker_order_id is NULL (client_order_id crash-recovery path). `import math` added for `math.isfinite()`. 10 tests added in `TestBrokerFillInvalidGuard` — one per invariant field + one for valid fill path.
