# Detect Incomplete FIFO Lot Coverage and Fail Closed

- **ID:** 0176
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`select_fifo_lots(ticker, shares_to_select)` stops when it runs out of stored lots, but it does not report whether it actually satisfied the requested share count. If the `cost_lots` table only contains 40 shares for a 100-share assignment, the function returns those 40 shares — a non-empty list — and `_lot_tax_friction()` treats the data as complete and available. The remaining 60 shares are invisible, and the computed friction can be understated by 60% or more. This is a P1 correctness bug.

## Proposed approach

**Option A (preferred): return completeness metadata from `select_fifo_lots()`**

Change the return type to include `shares_selected` and `complete`:

```python
def select_fifo_lots(ticker: str, shares_to_select: float) -> dict:
    """Returns: {lots: [...], shares_requested: float, shares_selected: float, complete: bool}"""
```

Then in `_lot_tax_friction()`:

```python
result = _adb_tax.select_fifo_lots(ticker, shares_to_assign)
if not result["complete"]:
    return TaxFrictionDetail(
        total_friction=0.0,
        reason=f"incomplete lot coverage: {result['shares_selected']:.0f}/{shares_to_assign} shares",
        available=False,
    )
fifo_lots = result["lots"]
```

**Option B (simpler if callers can't change):** check inside `_lot_tax_friction()` after the call:

```python
total_allocated = sum(lot["allocated"] for lot in fifo_lots)
if total_allocated < shares_to_assign - 0.01:   # allow float rounding
    return TaxFrictionDetail(available=False, reason="incomplete lot coverage", ...)
```

Option B avoids changing `select_fifo_lots()` but requires the check in every caller. Option A is cleaner if `select_fifo_lots()` is the canonical FIFO source.

Prefer Option A. Update all existing callers (`covered_call_rec._lot_tax_friction`, `serve.py` sell allocation) to use `result["lots"]` instead of the raw list.

## Touches

- `agent_db.py` — `select_fifo_lots()` return type
- `covered_call_rec.py` — `_lot_tax_friction()` completeness check
- `serve.py` — sell allocation caller of `select_fifo_lots()`
- `tests/test_cc_management.py` — test: 40-share lot for 100-share assignment → `available=False`
- `tests/test_agent_db.py` — test: completeness flag is True when lots satisfy request, False when short

## Done when

- [ ] `select_fifo_lots()` returns `{lots, shares_requested, shares_selected, complete}` (or equivalent)
- [ ] `_lot_tax_friction()` returns `available=False` when `complete=False`
- [ ] Serve.py sell allocation updated to unpack new return shape
- [ ] Test: insufficient lots → `available=False`, Gate 4 blocks assignment
- [ ] Test: exact lot coverage → `complete=True`, friction computed normally
- [ ] All existing tests pass
