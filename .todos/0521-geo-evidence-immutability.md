# Geo Evidence Immutability: INSERT OR IGNORE for Seeds, No Phantom Refresh

- **ID:** 0521
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0516

## Problem

0516 changed the `company_geo_profile` seed inserts to `INSERT OR REPLACE` so stale rows can be refreshed. But for the manual seed rows (ITOCF, MITSF), `INSERT OR REPLACE` runs every time `_init_ai_tables()` is called — which happens on every scorer startup. This silently resets `retrieved_at` to the current timestamp on every server restart, making the freshness field meaningless. A row seeded in 2026-09 will show `retrieved_at = "2026-11-01T03:00:00"` after a November restart even though the underlying geo data has not been verified since September.

`retrieved_at` should represent when the data was actually retrieved, not when the process last started.

## Proposed approach

**Two separate operations, not one:**

1. **Initial seed** (startup): use `INSERT OR IGNORE` — only writes if no row exists for the ticker. Never overwrites existing geo evidence.

```python
conn.execute("""
    INSERT OR IGNORE INTO company_geo_profile
        (ticker, primary_country, ..., data_source, source_date, retrieved_at, confidence, evidence_hash, notes)
    VALUES (?, ?, ..., ?, ?, ?, ?, ?, ?)
""", ("ITOCF", ..., "manual_seed", "2026-09", "2026-09-19T00:00:00", "medium", evidence_hash, "..."))
```

2. **Explicit refresh** (separate admin script or manual operation): `INSERT OR REPLACE` with a new `retrieved_at` — only used when a human has actually re-verified the geo facts and is recording the new retrieval.

This pattern means `retrieved_at` is only updated when there is a real human decision behind it. It also means the evidence hash can be used to detect when the material fields change between refreshes.

**No phantom `retrieved_at` reset**: the `_init_ai_tables()` seeding path must never write a current timestamp unless the row is being created for the first time (`INSERT OR IGNORE`).

## Touches

- `portfolio_ai.py` — `_init_ai_tables()` seed INSERT statements for ITOCF and MITSF

## Done when

- [ ] Seed INSERTs use `INSERT OR IGNORE` — existing rows are never overwritten on startup
- [ ] `retrieved_at` in seed rows reflects the date the data was sourced, not server start time
- [ ] No code path in `_init_ai_tables()` updates `retrieved_at` on an existing row
- [ ] Explicit refresh path (if needed) is a separate function or script, not `_init_ai_tables()`
