# Fix MTM Failure Integrity: No Synthetic Exits, Correct Daily Return

- **ID:** 0366
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0364

## Problem

Two related data-quality bugs in `book_mtm.py`:

### 1. Missing close at 63-session exit manufactures a trade

When a position expires (≥63 trading sessions held), the code fetches an
exact-date close and falls back to `avg_cost` if unavailable. It then
immediately emits a synthetic SELL at whichever price it got. If Yahoo Finance
fails for that ticker that evening, the simulator records a SELL at the
holder's cost basis — a break-even exit that never happened — and removes the
position from the holdings dict before the normal incomplete-price check runs.
The resulting NAV row may not be flagged `is_complete=0` because the
problematic position no longer appears among open holdings. This silently
manufactures a round-trip trade with zero P&L rather than preserving the
position for a real exit price next session.

### 2. Daily return references previous incomplete NAV row

The daily-return calculation queries:
```sql
SELECT total_nav FROM virtual_book_nav
WHERE book_id=? ORDER BY date DESC LIMIT 1
```
with no `is_complete=1` filter. An incomplete row (e.g. Tuesday with one price
missing) becomes the denominator for Wednesday's return. The dashboard
subsequently filters to `is_complete=1`, consuming Wednesday's persisted
`+3.06%` as though Tuesday's NAV were valid, silently distorting every
subsequent day's return and the cumulative volatility series.

## Proposed approach

### Fix 1 — Never manufacture a synthetic exit

```python
if sessions >= BOOK_HOLD_SESSIONS:
    exit_price = _get_closing_price(ticker, date_str)
    if exit_price is None:
        # Retain position; mark row incomplete; retry next valid session
        any_incomplete = True
        continue   # do NOT emit synthetic SELL
    _emit_synthetic_sell(book_id, ticker, exit_price, ...)
```

The position stays in the holdings dict and will be re-evaluated on the next
MTM run. Incomplete NAV rows are already written when `any_incomplete=True`, so
the row is correctly flagged.

### Fix 2 — Previous-NAV query must filter complete rows

```python
prev = conn.execute(
    """SELECT total_nav FROM virtual_book_nav
       WHERE book_id=? AND is_complete=1
       ORDER BY date DESC LIMIT 1""",
    (book_id,),
).fetchone()
daily_return = (total_nav / prev["total_nav"] - 1) if prev else None
```

If the current row itself is incomplete, write `daily_return = NULL` rather
than a potentially wrong value.

## Touches

- `agents/learning/book_mtm.py` — expired-position exit gate; previous-NAV query
- `tests/test_book_simulator.py` — test that unavailable exit price retains position; test that daily_return is NULL when current row incomplete; test that previous incomplete NAV is not used as daily-return denominator

## Done when

- [ ] When exact exit close is unavailable, position is retained and row is marked incomplete (no SELL emitted)
- [ ] `is_complete=1` filter applied to previous-NAV query before computing `daily_return`
- [ ] `daily_return = NULL` when the current row itself is incomplete
- [ ] Test: expired position with missing price → position present in next MTM run, no fills written
- [ ] Test: incomplete prior row → today's daily_return is computed against last complete row
- [ ] `python -m pytest tests/` passes with no regressions
