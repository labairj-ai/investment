# Add Daily Mark-to-Market NAV Job

- **ID:** 0351
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0346

## Problem

`virtual_book_nav` rows written at fill time use cost-basis values for open positions — `positions_json` contains average purchase cost, not closing price, and `spy_nav`/`daily_return` are left NULL. The acceptance criterion from 0346 ("open positions marked to market using closing prices") was not implemented. This means cumulative return, drawdown, and volatility derived from `virtual_book_nav` are economically wrong until a position is realized. `compute_book_stats()` also reconstructs intermediate NAV from `current_cash` rather than historical cash at each fill step, so the dynamic fallback path is also wrong.

## Proposed approach

- Write a nightly function (new `agents/learning/book_mtm.py` or extend `outcome_labeler.py`) that runs after market close (4:30 PM ET)
- For each book: reconstruct current holdings from `virtual_fills` (net qty per ticker, avg cost); fetch closing price for every held ticker via yfinance (same source as outcome labeler); compute `market_value = Σ(qty × close)`, `total_nav = cash + market_value`
- Fetch SPY close; store `spy_nav` indexed to $100k starting NAV
- Compute `daily_return = (total_nav_today / total_nav_yesterday) - 1`; write one `virtual_book_nav` row per book per date with all fields populated
- `serve.py` reads the `virtual_book_nav` date series directly; remove the cost-basis fallback reconstruction
- Remove "EXPERIMENTAL — cost-basis accounting" badge from `generate_dashboard.py` once live MTM rows cover the last 30 days
- Schedule via systemd timer on optiplex alongside the existing 8 PM nightly run (after outcome labeler)

## Touches

- `agents/learning/book_mtm.py` (new) or `agents/learning/outcome_labeler.py`
- `agent_db.py` — verify `spy_nav`, `daily_return` columns present in `virtual_book_nav`
- `serve.py` — read MTM rows; drop cost-basis reconstruction
- `generate_dashboard.py` — condition "experimental" badge on presence of real MTM rows
- `systemd/` — new or extended timer unit
- `tests/test_book_simulator.py` — test MTM values position at close price (not cost); daily_return non-null

## Done when

- [ ] After each market close, one `virtual_book_nav` row per book is written with positions valued at closing price (not cost)
- [ ] `spy_nav` and `daily_return` populated on every new row
- [ ] Dashboard reads `virtual_book_nav` time series; does not reconstruct cost-basis NAV from fills at serve time
- [ ] Cumulative return, drawdown, and relative performance all derived from the MTM NAV series
- [ ] "Experimental" badge removed or conditioned on presence of live MTM rows
- [ ] `python -m pytest tests/` passes with no regressions
