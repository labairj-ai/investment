# Account Snapshot open_order_notional Must Include Open SELL Notional

- **ID:** 0233
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`_write_account_snapshot()` (`execution_engine.py:187`) sets `open_order_notional = _open_buy_notional(account_id, conn)`. This is the reserved BUY cash — it does not include outstanding SELL commitments. The column name `open_order_notional` implies gross outstanding order exposure, but it only reflects the buy side. An account with $5,000 in open SELL orders shows `open_order_notional = 0` if no BUY orders exist.

`reserved_cash` is correctly buy-side only (sells don't consume cash), so it stays. But `open_order_notional` should be total gross committed order exposure: BUY + SELL.

## Proposed approach

- In `_write_account_snapshot()` (`execution_engine.py:166-205`): import `_open_sell_notional` from `risk_engine` alongside the existing `_open_buy_notional` import.
- Compute separately: `reserved_cash = _open_buy_notional(account_id, conn)` (unchanged) and `open_order_notional = reserved_cash + _open_sell_notional(account_id, conn)`.
- Update the INSERT/UPDATE statement to write the two values independently where they differ.
- Tests: account with $1,000 WORKING BUY and $1,500 WORKING SELL; assert `reserved_cash = $1,000`, `open_order_notional = $2,500` in `account_snapshots`.

## Touches

- `trade_engine/execution_engine.py` — `_write_account_snapshot()`
- `tests/test_trade_engine.py` — account snapshot notional tests

## Done when

- [x] `open_order_notional` in `account_snapshots` = `open_buy_notional + open_sell_notional`
- [x] `reserved_cash` in `account_snapshots` = `open_buy_notional` only (buy-side, unchanged)
- [x] `buying_power` still computed as `cash - reserved_cash` (unchanged)
- [x] Tests confirm both fields for an account holding BUY and SELL working orders
