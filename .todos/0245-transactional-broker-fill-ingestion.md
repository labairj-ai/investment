# Transactional Broker Fill Ingestion With Atomic Cursor Advance

- **ID:** 0245
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0242

## Problem

`initialize_trading_session()` inserts broker fills into the `fills` table but does not apply them to cash, positions, orders, or intent state. Fill-import exceptions are individually swallowed with `except: pass`, yet `last_fill_synced_at` is still advanced to the current time regardless. A failed fill import is therefore silently skipped on all future restarts. The 0242 acceptance criteria already required applying fills to account state — that story should be considered incomplete.

## Proposed approach

1. Create `apply_broker_fill(bf: BrokerFill, conn)` — one transactional path that atomically:
   - Inserts the fill into `fills`
   - Updates `orders.fill_qty` / `orders.fill_cash` / `orders.state`
   - Updates `position_snapshots` (qty, avg_cost, market_value)
   - Updates `trading_accounts.current_cash`
   - Updates `trade_intents.status`
   - Writes the `executed_actions` audit record
   - Commits — all or nothing
2. In `initialize_trading_session()`: call `apply_broker_fill()` per fill; if any fill fails, log and halt rather than continue.
3. Only advance `last_fill_synced_at` to `max(filled_at)` of successfully imported fills, not to `now`. This ensures a failed fill is retried on next restart.
4. Never use bare `except: pass` in reconciliation or fill-import paths.

## Touches

- `trade_engine/execution_engine.py` — `initialize_trading_session()`, new `apply_broker_fill()`
- `trade_engine/shadow_broker.py` — share `_apply_fill` logic or unify
- `agent_db.py` — schema already has the columns; verify no additions needed
- `tests/test_trade_engine.py`

## Done when

- [ ] `apply_broker_fill()` updates fills, order state, positions, cash, intent status, and audit record atomically
- [ ] `last_fill_synced_at` advances only to the max `filled_at` of successfully imported fills
- [ ] A fill-import failure halts the session (HALTED) rather than silently skipping
- [ ] No bare `except: pass` in fill-import or reconciliation code paths
- [ ] Tests confirm cash and positions are updated after fill import on reconnect
