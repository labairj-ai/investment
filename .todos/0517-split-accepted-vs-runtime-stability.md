# Split Accepted Validation From Runtime Stability Into Separate Tables

- **ID:** 0517
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0510

## Problem

`macro_dimension_stability` has `PRIMARY KEY (ticker, dim)`, so `INSERT OR REPLACE` from the routine scorer overwrites accepted validation rows with runtime_sampling rows. After the next weekly scoring pass, `_is_formally_usable()` queries for `validation_run_type='accepted_validation'` and finds nothing — the accepted evidence is silently destroyed. The current single-table design cannot support both an append-only validation record and a mutable runtime record.

## Proposed approach

Replace the single table with two:

**`macro_dimension_validation`** — append-only, one row per acceptance run × ticker × dim:
```sql
CREATE TABLE macro_dimension_validation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acceptance_record_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    dimension TEXT NOT NULL,
    mean_score REAL,
    stddev REAL,
    n_samples INTEGER,
    stability_class TEXT,
    config_version TEXT,
    config_hash TEXT,
    model_identity TEXT,
    recorded_at TEXT,
    UNIQUE(acceptance_record_id, ticker, dimension)
)
```
No DELETE or UPDATE ever runs on this table. The validator only INSERTs after a PASS verdict.

**`macro_dimension_runtime_stability`** — mutable, one row per ticker × dim:
```sql
CREATE TABLE macro_dimension_runtime_stability (
    ticker TEXT NOT NULL,
    dimension TEXT NOT NULL,
    mean_score REAL,
    stddev REAL,
    n_samples INTEGER,
    stability_class TEXT,
    updated_at TEXT,
    PRIMARY KEY (ticker, dimension)
)
```
The routine scorer uses `INSERT OR REPLACE` here. The validation script's failed runs also write here (with `stability_class` but no formal acceptance).

**Migration**: in `_init_ai_tables()`, copy existing `accepted_validation` rows from `macro_dimension_stability` to `macro_dimension_validation`, then copy `runtime_sampling` rows to `macro_dimension_runtime_stability`. Keep `macro_dimension_stability` for backward compat reads but stop writing to it.

Update all call sites:
- `_is_formally_usable()` → reads `macro_dimension_validation`
- `_n_samples_for_dim()` → reads `macro_dimension_runtime_stability` (falls back to `macro_dimension_validation`)
- Validation script → INSERTs to `macro_dimension_validation` after PASS
- Scorer → `INSERT OR REPLACE` into `macro_dimension_runtime_stability`

## Touches

- `portfolio_ai.py` — two new tables, migration, all read/write call sites
- `scripts/validate_macro_scorer.py` — writes to `macro_dimension_validation` after PASS only

## Done when

- [ ] `macro_dimension_validation` table exists; only PASS runs write to it
- [ ] `macro_dimension_runtime_stability` table exists; routine scorer writes here
- [ ] `INSERT OR REPLACE` from scorer cannot touch `macro_dimension_validation`
- [ ] Migration copies existing rows into correct tables on startup
- [ ] `_is_formally_usable()` reads `macro_dimension_validation` exclusively
