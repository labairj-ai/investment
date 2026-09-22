# Advance Fill Sync Cursor on All Observed Fills

- **ID:** 0567
- **Status:** done
- **Created:** 2026-09-22
- **Priority:** normal
- **Depends:** none

## Problem

`last_fill_synced_at` only advances when `apply_broker_fill()` returns `APPLIED`. If every fill in a batch returns `ALREADY_APPLIED` (e.g. fills manually seeded into the DB before the engine ran, as happened with Sep-15 SOXS fills), `max_filled_at` stays `None` and the cursor never moves. The engine then re-fetches the entire Alpaca fill history on every subsequent cycle start — in both `sync_broker_state()` and `initialize_trading_session()`. The Sep-15 state was repaired with a one-off SQL UPDATE, but the code path that produced it is unchanged.

## Proposed approach

After `apply_broker_fill()` returns successfully (without raising), update `max_filled_at` unconditionally — regardless of whether the result was `APPLIED` or `ALREADY_APPLIED`. Only skip the update when the call raises one of the integrity exceptions (`UnknownFillError`, `BrokerFillInvalid`, `OverfillError`, `ImpossibleSellError`); those must remain fail-closed and must not advance the cursor past the problematic fill.

Apply the identical change in two places:
- `sync_broker_state()` — ledger pull section (the `for _lf in _ledger` loop near the end)
- `initialize_trading_session()` — step 2-3 fill import loop

Add tests (new `test_fill_cursor.py` or extend `test_trade_engine.py`):
- All fills new → cursor advances to newest fill's `filled_at`
- All fills duplicates → cursor still advances to newest fill's `filled_at`
- Mix of new + duplicates → cursor reaches max across both sets
- Duplicate with a later timestamp than the newest new fill → cursor reaches that timestamp
- `UnknownFillError` mid-batch → cursor does NOT advance past the failing fill
- `BrokerFillInvalid` mid-batch → cursor does NOT advance past the invalid fill

Key invariant: `last_fill_synced_at = max(filled_at)` of all fills for which `apply_broker_fill()` did not raise, regardless of `APPLIED`/`ALREADY_APPLIED`.

## Touches

- `trade_engine/execution_engine.py` — `sync_broker_state()` and `initialize_trading_session()`
- `tests/test_trade_engine.py` or new `tests/test_fill_cursor.py`

## Done when

- [ ] `sync_broker_state()` advances `last_fill_synced_at` to `max(filled_at)` even when all fills return `ALREADY_APPLIED`
- [ ] `initialize_trading_session()` advances the cursor by the same logic
- [ ] Raising integrity exceptions still leaves the cursor at its pre-batch value
- [ ] All six test cases pass
- [ ] A fresh account that has only manually-seeded fills (order_id NULL) no longer re-fetches the full fill history on the second cycle
