# Tax-Data Exceptions Must Fail Closed

- **ID:** 0175
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

The broad `except Exception` handler in `_lot_tax_friction()` still returns:

```python
TaxFrictionDetail(total_friction=0.0, reason="", available=True)
```

This means a DB connection failure, a missing `cost_lots` table, an import error, or any other runtime exception is silently treated as "tax data loaded successfully, zero friction" — which is indistinguishable from a position that is genuinely all long-term lots with no avoidable friction. Gate 4 therefore passes, and assignment is allowed when the actual tax cost is unknown.

The empty-lots case correctly returns `available=False` (0171), but exceptions bypass that path entirely.

## Proposed approach

Change the exception handler so every exception path returns `available=False`:

```python
except Exception as exc:
    return TaxFrictionDetail(
        total_friction=0.0,
        reason=f"tax lot data unavailable: {type(exc).__name__}",
        available=False,
    )
```

Add a test that forces the DB call itself to throw (monkeypatch `agent_db.select_fifo_lots` to raise `sqlite3.OperationalError`) and asserts:
- `detail.available is False`
- `"unavailable" in detail.reason`
- Gate 4 blocks assignment with the context built from this detail

## Touches

- `covered_call_rec.py` — `_lot_tax_friction()` exception handler
- `tests/test_cc_management.py` — new test: DB exception → `available=False` → Gate 4 blocks

## Done when

- [ ] Exception handler returns `available=False` with a non-empty reason string
- [ ] Test: monkeypatched `select_fifo_lots` raises → `available=False`
- [ ] Test: Gate 4 blocks assignment when `available=False` due to exception
- [ ] All existing tests pass
