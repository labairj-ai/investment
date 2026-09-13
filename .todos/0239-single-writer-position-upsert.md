# Replace Fragile INSERT OR IGNORE + Conditional UPDATE with Atomic UPSERT

- **ID:** 0239
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`_apply_fill()` in `shadow_broker.py` (line 253-278) uses `INSERT OR IGNORE INTO position_snapshots` followed by a conditional `UPDATE ... WHERE qty != fill.qty` to handle the race between a fresh insert and a concurrent writer. This logic is not a robust concurrency primitive:

If another writer creates a position with exactly the same quantity as the incoming fill, the `qty != fill.qty` guard cannot distinguish "I just inserted this" from "another process inserted an equal-size position." The result is a silent no-op: the position's `avg_cost` and mark are not updated, and cash is already deducted.

The practical fix is to establish a rule enforced architecturally: **one process is the sole writer for execution state**. Broker callbacks and websocket events must be queued into that single writer rather than mutating portfolio state from arbitrary threads. This eliminates the ambiguity rather than trying to detect it.

At the code level, replace the two-step INSERT + conditional UPDATE with a single `INSERT ... ON CONFLICT DO UPDATE` (SQLite UPSERT syntax), which is atomic:

## Proposed approach

Replace the existing new-position block (lines 251-278) in `_apply_fill()`:

```python
# Single atomic UPSERT — no race between INSERT and UPDATE (0239)
self._conn.execute(
    """INSERT INTO position_snapshots
           (account_id, symbol, qty, avg_cost, instrument_type, as_of,
            market_price, market_value, price_as_of)
       VALUES (?, ?, ?, ?, 'EQUITY', ?, ?, ?, ?)
       ON CONFLICT(account_id, symbol) DO UPDATE SET
           avg_cost = (excluded.qty * excluded.avg_cost + qty * avg_cost)
                      / (excluded.qty + qty),
           qty      = qty + excluded.qty,
           as_of    = excluded.as_of""",
    (fill.account_id, fill.symbol, fill.qty, fill.price,
     fill.filled_at, fill.price, fill.qty * fill.price, fill.filled_at),
)
```

For the existing-position path (update only), keep the existing `SELECT + UPDATE` — that path already has all necessary data and is already conditional on `existing_pos`.

Add a comment documenting the single-writer invariant so future contributors understand why distributed locking is intentionally absent.

## Touches

- `trade_engine/shadow_broker.py` — `_apply_fill()`, new-position INSERT block (lines ~251-278)
- `tests/test_trade_engine.py` — verify existing fill/position tests still pass; optionally add a test that two fills to the same symbol in sequence produce a single correctly-averaged position row

## Done when

- [ ] `INSERT OR IGNORE` + conditional `UPDATE` replaced with single `INSERT ... ON CONFLICT DO UPDATE`
- [ ] All existing fill and position tests pass
- [ ] New test: two sequential fills to same symbol produce one position row with correct avg_cost
- [ ] Single-writer invariant documented in comment
