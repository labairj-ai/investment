# Keep Portfolio Marks Coherent After Each Fill in Same Cycle

- **ID:** 0231
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`_apply_fill()` in `shadow_broker.py:236-248` updates `qty`, `avg_cost`, and `as_of` on `position_snapshots` but does not update `market_price`, `market_value`, or `price_as_of`. If a BUY fill doubles a position from 10 to 20 shares while `market_price = $100`, `market_value` remains `$1,000` — the next intent processed in the same cycle sees 20 shares but only $1,000 exposure. This understates concentration, NAV, and position-weight checks for all subsequent decisions in the cycle.

## Proposed approach

- After updating `qty` in `_apply_fill()`, also update `market_value`:
  - **Existing position** (UPDATE path, `shadow_broker.py:237-241`): if `market_price` is already set on the row, set `market_value = new_qty × market_price`. Fetch `market_price` from the existing row before the update and include it in the UPDATE SET clause.
  - **New position** (INSERT path, `shadow_broker.py:242-268`): use the fill price as the initial mark: `market_price = fill.price`, `market_value = fill.qty × fill.price`, `price_as_of = fill.filled_at`. The next external quote refresh will replace this.
- The `price_as_of` written here is the fill timestamp, which is an honest "this is when we last had a price signal," not a stale NULL.
- Tests: BUY 10 shares into existing 10-share position; assert `market_value` is immediately `20 × market_price`, not the pre-fill `10 × market_price`.

## Touches

- `trade_engine/shadow_broker.py` — `_apply_fill()`, existing-position UPDATE, new-position INSERT
- `tests/test_trade_engine.py` — same-cycle mark coherence tests

## Done when

- [x] After a BUY fill on an existing position, `market_value = new_qty × existing market_price`
- [x] After a BUY fill creating a new position, `market_price = fill.price`, `market_value = qty × fill.price`, `price_as_of = fill.filled_at`
- [x] After a SELL fill, `market_value` is recomputed for the remaining qty (or row deleted if qty ≤ 0)
- [x] Tests confirm a second intent in the same cycle sees the updated exposure
