# Treat Unpriced Positions as Stale, Not Safe

- **ID:** 0228
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`_stale_position_symbols()` only flags positions where `market_price IS NOT NULL` but `price_as_of` is old or missing. Positions with `market_price IS NULL` are deliberately skipped as "unpriced." The consequence: a held position that has never successfully refreshed (e.g., yfinance fails every cycle) keeps its `avg_cost`-based NAV and new trades get authorized against it indefinitely. The 0221 story acceptance criteria state "positions with NULL price_as_of block authorization" — the implementation contradicts that.

Unknown price is not safer than stale price. The correct hierarchy is: fresh → usable; stale → block; unknown → block.

Also: `run_execution_cycle()` does not return the `market_state` field that todo 0221 required. Only `new_intents_blocked` and `stale_symbols` are present.

## Proposed approach

- In `_stale_position_symbols()` (`risk_engine.py:190`): change the WHERE clause to flag positions where `market_price IS NULL OR price_as_of IS NULL OR price_as_of < ?` (any held row with missing or old data is stale).
- In `_check_portfolio_mark_freshness()` (`execution_engine.py:135`): similarly remove the `if market_price is None: continue` shortcut.
- In `run_execution_cycle()`: add `market_state` to the return dict: `"fresh"` when no stale symbols, `"stale"` when blocked.
- Tests: reverse `test_unpriced_position_does_not_trigger_stale` — it should now assert the unpriced position IS stale and blocks authorization. Add a test that a position with a successful recent refresh (`market_price` set, fresh `price_as_of`) does NOT block.

## Touches

- `trade_engine/risk_engine.py` — `_stale_position_symbols()`
- `trade_engine/execution_engine.py` — `_check_portfolio_mark_freshness()`, `run_execution_cycle()`
- `tests/test_trade_engine.py` — reverse existing unpriced test, add fresh-mark test

## Done when

- [x] Held position with `market_price IS NULL` triggers `RISK_STATE_STALE` and blocks new intent authorization
- [x] Held position with `market_price` set and fresh `price_as_of` passes the stale check
- [x] `run_execution_cycle()` return dict includes `market_state: "fresh" | "stale"`
- [x] Reversed test passes (unpriced IS stale)
- [x] All existing tests updated and passing
