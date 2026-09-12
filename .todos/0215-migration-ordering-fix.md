# Fix Migration Ordering: Trade-Engine Tables Before _new_cols ALTER TABLE

- **ID:** 0215
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`agent_db.migrate()` runs `_new_cols` ALTER TABLE statements (line 492) before calling `_migrate_trade_engine(conn)` (line 567). On a fresh database, the trade-engine tables (`fills`, `position_snapshots`, `trading_accounts`, `orders`, `risk_decisions`, `trade_intents`) don't exist yet when the ALTER TABLE loop runs. The ALTERs silently fail (caught by `except sqlite3.OperationalError: pass`). `_migrate_trade_engine()` then creates the tables in their base schema — without the B0 columns (`cost_basis`, `market_value`, `nav_high_water`, `policy_hash`, etc.). The same ordering bug affects the unique indexes on `orders(intent_id)` and `position_snapshots(account_id, symbol)`.

Tests don't catch this because `test_trade_engine.py` constructs the final schema directly in `_make_conn()` rather than calling `migrate()`.

## Proposed approach

1. Move the `_migrate_trade_engine(conn)` call to run **before** the `_new_cols` loop — ideally immediately after the main `conn.executescript(...)` that creates agent tables (~line 411). Order becomes:
   ```
   1. executescript(...) — create all agent tables
   2. _migrate_trade_engine(conn) — create trade-engine tables
   3. _new_cols ALTER TABLE loop — add incremental columns to ALL tables
   4. unique index creation blocks
   5. data migrations (ev_ebitda→ev_ebit, etc.)
   ```

2. Move the `idx_orders_intent_id` and `idx_positions_account_symbol` index creation to after `_migrate_trade_engine()`.

3. Add three migration tests in `tests/test_trade_engine.py` (or a new `tests/test_migration.py`):
   - `test_fresh_database_migration()` — create empty SQLite in-memory, call `migrate()`, assert all B0 columns present on trade-engine tables
   - `test_migrate_twice_is_idempotent()` — call `migrate()` twice on same DB, no error, same schema
   - `test_base_schema_to_current_migration()` — manually create trade-engine tables in base form (no B0 cols), then call `migrate()`, assert B0 cols are added

## Touches

- `agent_db.py` — reorder calls within `migrate()`
- `tests/test_trade_engine.py` or new `tests/test_migration.py` — 3 new migration tests

## Done when

- [ ] Fresh SQLite DB after `migrate()` has `fills.cost_basis`, `position_snapshots.market_value`, `trading_accounts.nav_high_water`, `orders.market_data_status`, `trade_intents.policy_hash`, `risk_decisions.uuid_id`
- [ ] `migrate()` on a fresh DB seeds `AGENTIC_SHADOW_01` correctly
- [ ] Calling `migrate()` twice produces no error
- [ ] Existing optiplex DB (with B0 columns already present) migrates without error
- [ ] All 391 existing tests still pass
