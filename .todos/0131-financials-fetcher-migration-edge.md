# Fix financials_fetcher.py Standalone Migration Edge Case

- **ID:** 0131
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

Running `python financials_fetcher.py` directly against an older database (one that predates the `shares_period_end` column) will fail because `_init_tables()` in `financials_fetcher.py` creates `company_financials` with the current schema, but `historical_valuation_metrics` and related tables may have been created by an older `agent_db.migrate()` that lacked newer columns. If `fetch_all()` is called before `agent_db.migrate()` runs, the DB may be in a partially migrated state.

The root cause: `fetch_all()` calls `_init_tables()` (which handles `company_financials`) but does not call `agent_db.migrate()` first, so any columns added by agent_db migrations (e.g. `shares_period_end` in `company_financials` if it was ever migrated there, or any helper tables) may be missing.

## Proposed approach

- At the top of `fetch_all()`, call `agent_db.migrate()` before `_init_tables()`. This is idempotent (`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE IF NOT EXISTS` semantics) so it is safe to call multiple times.
- Alternatively, ensure `_init_tables()` itself includes all columns that `agent_db.migrate()` would add to `company_financials`, so the two paths converge.
- Add a test (`test_financials.py`) that runs `financials_fetcher.fetch_all()` against a DB that has been migrated by an older version (simulated by creating `company_financials` without `shares_period_end`) and verifies it completes without error and the column is present afterward.

## Touches

- `financials_fetcher.py` — `fetch_all()` entry point
- `agent_db.py` — verify `migrate()` is safe to call redundantly
- `tests/test_financials.py` — add migration-edge integration test

## Done when

- [ ] `fetch_all()` calls `agent_db.migrate()` before `_init_tables()`
- [ ] Running `python financials_fetcher.py` against a DB without `shares_period_end` completes without OperationalError
- [ ] Test simulates old-schema DB (missing column) and verifies `fetch_all()` succeeds
