# Use MTM Ledger as Dashboard Source of Truth

- **ID:** 0359
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0351

## Problem

`book_mtm.py` (0351) now correctly writes `virtual_book_nav` rows with:
- `total_nav`
- `spy_nav`
- `daily_return`
- dated records per book

But `serve.py` still reads from `virtual_fills` directly via `_book_portfolio_stats()`, which:
- Reconstructs NAV from cost basis only (`nav_series = []  # cost-basis NAV (no mark-to-market)`)
- Returns `cumulative_return_cost_basis` in the API response
- Never queries `virtual_book_nav`

Meanwhile, when `mtm_rows_available()` returns `True`, the dashboard can remove the "EXPERIMENTAL — cost-basis accounting" warning badge — **while still displaying cost-basis numbers**. This means the warning disappears before the data improves.

The fix has two parts:
1. Wire `_book_portfolio_stats()` to read from `virtual_book_nav` when rows are available
2. Keep the experimental badge until the API actually switches to MTM reads

## Proposed approach

### `serve.py` — rewrite `_book_portfolio_stats()`

When `mtm_rows_available(conn)` is True, query `virtual_book_nav` for:
- **NAV series** — `total_nav` ordered by `date` per book
- **Cumulative return** — `(nav[-1] - nav[0]) / nav[0]` or `(nav / starting_cash) - 1`
- **SPY benchmark series** — `spy_nav` from the same rows
- **Daily returns** — `daily_return` column directly
- **Max drawdown** — compute from NAV series
- **Volatility** — std(daily_return) × √252

When `mtm_rows_available()` is False, fall back to cost-basis reconstruction with the experimental label.

### `serve.py` — update `mtm_nav_available` flag logic

Only set `mtm_nav_available = True` in the JSON response after the portfolio stats themselves are reading from MTM NAV. The flag controls the dashboard badge — it must track the actual data source, not just the presence of rows.

### `generate_dashboard.py` — badge condition

The current condition in `generate_dashboard.py`:
```javascript
var _expBadge = (d.mtm_nav_available)
  ? ''
  : '<span ...>EXPERIMENTAL — cost-basis accounting</span>';
```
This is correct once `mtm_nav_available` correctly tracks the data source. No change needed here once serve.py is fixed.

### What to use fills for (read-only, not for return calcs)

- Trade count
- Turnover
- Win rate / profit factor (realized fills only)
- Execution statistics (fill vs mid, slippage)
- Per-ticker holding period distribution

## Touches

- `serve.py` — `_book_portfolio_stats()` reads from `virtual_book_nav` when available; `mtm_nav_available` flag gated on actual data source
- `generate_dashboard.py` — no change needed if serve.py is correct
- `tests/test_book_simulator.py` or new `tests/test_serve_books.py` — assert API returns MTM-sourced NAV series when rows exist; assert badge flag is False while still cost-basis

## Done when

- [ ] `_book_portfolio_stats()` queries `virtual_book_nav` for NAV series, cumulative return, SPY benchmark, max drawdown when MTM rows are available
- [ ] `mtm_nav_available` in API response is `True` only when stats are actually from MTM source
- [ ] Cost-basis fallback still works when no MTM rows exist
- [ ] "EXPERIMENTAL" badge remains visible until MTM data is the actual source
- [ ] `python -m pytest tests/` passes with no regressions
