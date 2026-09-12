# Trade Engine DB Schema: New Tables for Shadow Execution

- **ID:** 0190
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

The current `investment.db` has no concept of a named trading account, a formal trade intent, pre-trade risk decisions, or a simulated order/fill lifecycle. Before any code in `trade_engine/` can work, the schema must exist.

All new tables live in `investment.db` during shadow mode — no second physical database yet. The existing tables are untouched; migrations are additive only.

## Proposed approach

Add a `migrate_trade_engine()` function in `agent_db.py` (or a new `trade_engine/db.py`) called from `migrate()` that creates the following tables with `CREATE TABLE IF NOT EXISTS`:

```sql
-- Named accounts (AGENTIC_SHADOW_01 initially)
trading_accounts (
    account_id TEXT PRIMARY KEY,
    name TEXT,
    mode TEXT,               -- 'shadow' | 'paper' | 'live'
    starting_capital REAL,
    current_cash REAL,
    broker TEXT,             -- NULL for shadow
    trading_enabled INTEGER, -- 0/1
    policy_version TEXT,
    created_at TEXT
)

-- Machine-readable trade proposals (one per actionable recommendation)
trade_intents (
    intent_id TEXT PRIMARY KEY,  -- UUID
    account_id TEXT REFERENCES trading_accounts,
    recommendation_id INTEGER REFERENCES recommendations,
    agent_run_id INTEGER,
    instrument_type TEXT,        -- 'EQUITY' | 'OPTION'
    symbol TEXT,
    side TEXT,                   -- 'BUY' | 'SELL' | 'SELL_TO_OPEN' | 'BUY_TO_CLOSE'
    quantity REAL,               -- shares for equity
    contracts INTEGER,           -- for options
    option_type TEXT,            -- 'CALL' | 'PUT' | NULL
    strike REAL,
    expiration TEXT,
    order_type TEXT,             -- 'LIMIT' | 'MARKET'
    limit_price REAL,
    time_in_force TEXT,          -- 'DAY' | 'GTC'
    strategy TEXT,
    thesis_version INTEGER,
    strategy_config_hash TEXT,
    portfolio_snapshot_id TEXT,
    valid_until TEXT,
    created_at TEXT,
    status TEXT                  -- 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED' | 'FILLED'
)

-- Per-rule risk check results for every intent
risk_decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id TEXT REFERENCES trade_intents,
    decision TEXT,               -- 'APPROVED' | 'REJECTED'
    checks_json TEXT,            -- JSON array of {rule, limit, before, after, result, reason}
    evaluated_at TEXT
)

-- Order lifecycle (one row per order, updated in place as state changes)
orders (
    order_id TEXT PRIMARY KEY,   -- UUID
    intent_id TEXT REFERENCES trade_intents,
    account_id TEXT,
    symbol TEXT,
    side TEXT,
    quantity REAL,
    contracts INTEGER,
    order_type TEXT,
    limit_price REAL,
    state TEXT,                  -- PENDING | SUBMITTED | WORKING | PARTIALLY_FILLED |
                                 -- FILLED | CANCELLED | REJECTED | EXPIRED | ERROR
    broker_order_id TEXT,
    submitted_at TEXT,
    updated_at TEXT,
    fill_qty REAL DEFAULT 0,
    fill_cash REAL DEFAULT 0
)

-- Individual fill events (immutable)
fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT REFERENCES orders,
    account_id TEXT,
    symbol TEXT,
    side TEXT,
    qty REAL,
    price REAL,
    fee REAL DEFAULT 0,
    fill_source TEXT,            -- 'shadow' | 'paper' | 'live'
    filled_at TEXT
)

-- Daily/periodic account state snapshots
account_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    cash REAL,
    nav REAL,
    buying_power REAL,
    snapshot_at TEXT
)

-- Agentic portfolio positions (maintained by execution engine from fills)
position_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    symbol TEXT,
    qty REAL,
    avg_cost REAL,
    instrument_type TEXT,
    as_of TEXT
)
```

The AGENTIC_SHADOW_01 account row should be inserted as a seed record if absent.

## Touches

- `agent_db.py` — `migrate()` calls new `_migrate_trade_engine()` helper
- `trade_engine/db.py` (optional home for schema-creation logic)

## Done when

- [ ] All 7 tables created by `migrate()` with no errors on fresh or existing DB
- [ ] AGENTIC_SHADOW_01 seed row inserted if not already present
- [ ] No existing table or index is modified
- [ ] `SELECT * FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'` returns the seed row
- [ ] Tests verify schema existence and seed data
