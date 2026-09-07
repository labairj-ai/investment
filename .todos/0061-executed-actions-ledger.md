# Executed Actions Ledger

- **ID:** 0061
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** P0
- **Depends:** none

## Problem

Accepting a recommendation and executing it are two distinct events, but the system treats them as simultaneous. An "accepted EXIT" immediately sets `actual_return = 0` in the outcome evaluator — but the user may not have sold for days. A "rejected" recommendation assumes permanent hold. TRIM/ALLOCATE/REBALANCE outcomes are all evaluated as if the user did nothing.

Without an execution ledger, performance measurement is fiction: the system cannot know what actually happened in the portfolio after any recommendation was made.

## Proposed approach

### 1. Schema

Add `executed_actions` table to `agent_db.py`:

```sql
CREATE TABLE IF NOT EXISTS executed_actions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id   INTEGER REFERENCES recommendations(id),
    ticker              TEXT NOT NULL,
    action              TEXT NOT NULL,          -- EXIT, TRIM, ALLOCATE, SELL_CC, etc.
    quantity            REAL,                   -- shares for equity; contracts for CC
    execution_price     REAL,                   -- price per share / option strike reference
    execution_date      TEXT NOT NULL,          -- YYYY-MM-DD
    fees                REAL DEFAULT 0,
    -- CC-specific fields
    strike              REAL,
    expiration          TEXT,
    premium             REAL,
    contracts           INTEGER,
    -- metadata
    tax_lot_ids         TEXT,                   -- JSON array of lot IDs affected
    notes               TEXT,
    source              TEXT DEFAULT 'manual',  -- 'manual' | 'broker_import'
    created_at          REAL NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_executed_actions_rec
    ON executed_actions (recommendation_id);
CREATE INDEX IF NOT EXISTS idx_executed_actions_ticker_date
    ON executed_actions (ticker, execution_date DESC);
```

### 2. agent_db helpers

- `insert_executed_action(recommendation_id, ticker, action, ...)` → id
- `get_executions_for_rec(recommendation_id)` → list[dict]
- `get_executions_for_ticker(ticker, since_date)` → list[dict]

### 3. Dashboard UI

Add a minimal "Record Execution" form to the recommendation detail view (same pattern as the existing Accept/Reject buttons). Fields: execution_date, price, quantity (pre-filled from recommendation payload where possible).

### 4. Outcome Evaluator integration

In `_compute_scenarios()`, if `get_executions_for_rec(rec_id)` returns results, use execution data instead of assumptions:
- `actual_r`: compute from actual execution_price and execution_date (not rec creation date)
- `actual_is_estimated = False`

## Touches

- `agent_db.py` — schema migration, insert/get helpers
- `agents/outcome_evaluator.py` — use execution record when available
- `serve.py` — new `/api/recommendations/<id>/execute` POST endpoint
- `static/` or template — "Record Execution" UI on recommendation card

## Done when

- [ ] `executed_actions` table created in DB migration
- [ ] `insert_executed_action()` and `get_executions_for_rec()` helpers exist
- [ ] Dashboard has "Record Execution" form on recommendation detail view
- [ ] Outcome evaluator uses execution_price/execution_date when execution record exists
- [ ] `actual_is_estimated = False` when execution record is present
- [ ] **Backend QA:** record an execution manually; verify outcome_evaluator picks it up
- [ ] **Frontend QA:** "Record Execution" form submits correctly; dashboard refreshes
- [ ] **No service regression:** existing Accept/Reject flow unchanged
