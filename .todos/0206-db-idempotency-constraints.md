# DB-Enforced Idempotency: Unique Indexes on Orders and Positions

- **ID:** 0206
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

Application-level idempotency (`submit_order()` checks for existing order by `intent_id`) is correct but not sufficient. If two scheduler processes run concurrently or a race condition occurs between the SELECT and INSERT, both can observe "no existing order" and insert duplicate rows. There are no database constraints to catch this.

Similarly, `position_snapshots` has no uniqueness constraint on `(account_id, symbol)`. A bug could silently create two rows for the same position, making balance calculations wrong.

## Proposed approach

**`orders` table**: add unique index on `intent_id`:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_intent_id
ON orders (intent_id);
```

Change `submit_order()` INSERT to:
```sql
INSERT OR IGNORE INTO orders (...) VALUES (...)
```
Then re-query the row afterward to return the canonical Order (whether just-inserted or pre-existing).

**`position_snapshots` table**: add unique index on `(account_id, symbol)`:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_account_symbol
ON position_snapshots (account_id, symbol);
```

Change position INSERT in `_apply_fill()` to:
```sql
INSERT OR IGNORE INTO position_snapshots (account_id, symbol, qty, avg_cost, ...) VALUES (...)
```
followed by an UPDATE for the running balance — or use `INSERT ... ON CONFLICT(account_id, symbol) DO UPDATE SET qty=...`.

**`trade_intents` table**: already has TEXT PK `intent_id`, which provides uniqueness. Document this explicitly.

## Touches

- `agent_db.py` — add both unique indexes in `_migrate_trade_engine()`
- `trade_engine/shadow_broker.py` — change INSERT to `INSERT OR IGNORE`, re-query after
- `tests/test_trade_engine.py` — add concurrent-insert test: two calls to `submit_order()` for same intent → one row only

## Done when

- [ ] `idx_orders_intent_id` unique index exists (verified via `SELECT * FROM sqlite_master`)
- [ ] `idx_positions_account_symbol` unique index exists
- [ ] `submit_order()` uses `INSERT OR IGNORE`; concurrent calls return same order_id
- [ ] `_apply_fill()` position INSERT uses conflict handling; no duplicate position rows possible
- [ ] Test: call `submit_order()` twice for same intent concurrently → exactly one row in orders
- [ ] Test: two fills for same symbol → one position row with accumulated qty
