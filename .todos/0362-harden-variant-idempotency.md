# Harden Variant Idempotency Lookup and Insert

- **ID:** 0362
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0352

## Problem

The DB uniqueness constraint from 0352 is correct:
```sql
UNIQUE(account_id, decision_variant_id)
WHERE decision_variant_id IS NOT NULL
```

But the pre-insert lookup query in `intent_builder.py` is:
```python
"SELECT * FROM trade_intents WHERE decision_variant_id=? LIMIT 1"
```

This is missing `account_id`. With two paper challenger accounts consuming the same decision variant, account A's lookup could return account B's intent, and B would never get its own intent created.

Additionally, the INSERT is a plain `INSERT` — a concurrent race between two execution workers (e.g. two trade runners triggered close together) would hit the unique constraint and raise rather than resolving cleanly.

## Proposed approach

### Fix the lookup query

```python
existing = conn.execute(
    "SELECT * FROM trade_intents WHERE account_id=? AND decision_variant_id=? LIMIT 1",
    (account_id, variant_id),
).fetchone()
```

### Use INSERT OR IGNORE + re-query pattern

Matches the pattern already used elsewhere in the engine:

```python
conn.execute(
    """INSERT OR IGNORE INTO trade_intents
       (intent_id, account_id, decision_variant_id, ...)
       VALUES (?, ?, ?, ...)""",
    (...),
)
conn.commit()
# Re-query the authoritative row (may be ours or a concurrent insert)
row = conn.execute(
    "SELECT * FROM trade_intents WHERE account_id=? AND decision_variant_id=?",
    (account_id, variant_id),
).fetchone()
return TradeIntent.from_db_row(row)
```

This is safe under concurrent workers: if two workers race, one INSERT is silently ignored, and both re-query the same canonical row.

### Test: two accounts, same variant

```python
def test_two_accounts_same_variant(mem_db, ...):
    # Insert same decision_variant_id, two different accounts
    intent_a = build_intent_from_variant(variant_id, "ACCOUNT_A", policy, conn)
    intent_b = build_intent_from_variant(variant_id, "ACCOUNT_B", policy, conn)
    assert intent_a.intent_id != intent_b.intent_id
    assert intent_a.account_id == "ACCOUNT_A"
    assert intent_b.account_id == "ACCOUNT_B"
```

### Test: concurrent builders (simulated)

Insert the intent row directly before calling `build_intent_from_variant()` — simulates the race:
```python
# Pre-insert to simulate concurrent worker
conn.execute("INSERT INTO trade_intents (...) VALUES (...)", (...))
conn.commit()
# Second builder should return the existing row, not raise
result = build_intent_from_variant(variant_id, account_id, policy, conn)
assert result is not None
```

## Touches

- `trade_engine/intent_builder.py` — `build_intent_from_variant()`: scope lookup by `account_id + decision_variant_id`; replace plain INSERT with INSERT OR IGNORE + re-query
- `tests/test_trade_engine.py` or `tests/test_calibration.py` — two-account test; concurrent-insert race test

## Done when

- [ ] Lookup query includes `account_id` in WHERE clause
- [ ] INSERT uses `INSERT OR IGNORE`; post-insert re-query returns authoritative row
- [ ] Test: two accounts with same variant_id each get their own intent
- [ ] Test: pre-inserted row (simulated race) causes second builder to return existing row rather than raising
- [ ] `python -m pytest tests/` passes with no regressions
