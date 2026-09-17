# Extract Canonical FIFO Lot Selector into agent_db

- **ID:** 0167
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** low
- **Depends:** none

## Problem

`serve.py` (sell allocation, ~line 430) and `covered_call_rec._lot_tax_friction` (~line 919) each contain separate inline FIFO lot-selection walks. If the two implementations ever diverge — in how they handle fractional shares, loss lots, or ordering — CC assignment and sell tracking will disagree on which lots are consumed, producing inconsistent tax calculations.

## Proposed approach

Add a shared function to `agent_db.py`:

```python
def select_fifo_lots(
    ticker: str,
    shares_to_select: float,
    as_of_date: str | None = None,   # ISO date; defaults to today
) -> list[dict]:
    """Return lots consumed by FIFO up to shares_to_select.

    Each returned dict has: purchase_date, cost_per_share, shares (original),
    allocated (shares consumed from this lot).
    Stops when shares_to_select is satisfied. Uses ORDER BY purchase_date ASC.
    """
```

Then update both callers:
- `covered_call_rec._lot_tax_friction`: replace the inline `for lot in lots` walk with `agent_db.select_fifo_lots(ticker, shares_to_assign)`
- `serve.py` sell allocation loop: replace the inline walk with `select_fifo_lots(ticker, total_shares_sold)`

The gain/LT-classification logic stays in each caller; the shared function only handles lot ordering and allocation arithmetic.

## Touches

- `agent_db.py`
- `covered_call_rec.py`
- `serve.py`
- `tests/test_agent_db.py` (or new test file for `select_fifo_lots`)

## Done when

- [ ] `agent_db.select_fifo_lots()` exists and handles partial lot allocation correctly
- [ ] `covered_call_rec._lot_tax_friction` uses `select_fifo_lots` instead of its inline walk
- [ ] `serve.py` sell allocation uses `select_fifo_lots` instead of its inline walk
- [ ] Existing tests for `_lot_tax_friction` and sell allocation pass unchanged
