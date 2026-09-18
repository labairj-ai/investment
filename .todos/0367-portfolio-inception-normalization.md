# Normalize Virtual Book Returns to Inception Starting Capital

- **ID:** 0367
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0359

## Problem

`_book_portfolio_stats()` in `serve.py` computes cumulative return as:

```python
starting = navs[0]  # first MTM row ever written
cum_return = (navs[-1] - starting) / starting
```

and SPY cumulative return uses the first `spy_nav` value similarly.

This drops whatever return occurred between portfolio inception (when the first
virtual fill was recorded) and the first successful MTM row. If the first MTM
run fails or is incomplete, the baseline shifts and cumulative returns will be
permanently wrong. Maximum-drawdown calculations also miss any loss that
happened before the first complete MTM row.

## Proposed approach

### Option A — Explicit inception row (preferred)

When `book_simulator.py` records the first BUY fill for a book (or when the
book is first created), write an inception `virtual_book_nav` row:

```sql
INSERT OR IGNORE INTO virtual_book_nav
    (book_id, date, total_nav, spy_nav, daily_return, is_complete)
VALUES
    (?, <inception_date>, 100000.0, 100.0, NULL, 1)
```

where `100000.0` is the book's `starting_cash` and `100.0` is SPY indexed at
100. All downstream calculations naturally divide by this row.

### Option B — Calculate against `starting_cash` in `_book_portfolio_stats()`

```python
book_row = conn.execute(
    "SELECT starting_cash FROM virtual_books WHERE book_id=?", (book_id,)
).fetchone()
starting = book_row["starting_cash"] if book_row else navs[0]
cum_return = (navs[-1] - starting) / starting
```

SPY: index the first spy_nav value to the same inception date. Either store
`spy_starting` at inception or use `navs[-1] / navs[0] * spy_navs[0] / spy_navs[-1]`
as a relative benchmark.

Option A is cleaner because it makes the drawdown calculation correct
automatically (the $100k point is included in the series).

### Open question

Should `inception_date` be the date of the first BUY fill or the date the
`virtual_books` row was created? Using the first fill avoids a phantom
inception row for books that have no fills yet.

## Touches

- `agents/learning/book_simulator.py` — write inception NAV row on first BUY fill
- `agents/learning/book_mtm.py` — or write inception row at first MTM run if no row exists
- `serve.py` — `_book_portfolio_stats()` denominator uses inception row or `starting_cash`
- `agent_db.py` — no schema change needed for Option A; Option B needs no changes
- `tests/test_book_simulator.py` — test that cumulative return is 0% when NAV equals starting_cash

## Done when

- [ ] Cumulative return of 0% produced when book NAV equals `starting_cash`
- [ ] Any return between inception and first MTM row is included in cumulative return
- [ ] Max-drawdown calculation includes the $100k / `starting_cash` starting point
- [ ] SPY cumulative return indexed from same inception point as portfolio NAV
- [ ] `python -m pytest tests/` passes with no regressions
