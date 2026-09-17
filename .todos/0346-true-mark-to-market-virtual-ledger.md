# True Mark-to-Market Virtual Ledger

- **ID:** 0346
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0340

## Problem

The current `book_simulator.py` and `/api/learning/champion-challenger` portfolio calculations have three material accounting errors that make cumulative return and drawdown unreliable:

1. **Open positions valued at cost basis, not market price.** If GRMN rises 25% while held, the reported NAV barely moves. Reported return understates (or overstates, on losses) actual economic performance.

2. **SELL/EXIT cash flows are wrong.** `fill_price = price × (1 + slippage_pct)` applies positive slippage regardless of direction; SELL fills should apply negative slippage (adverse for the seller). Cash is always *decremented* by `qty × fill_price`, so a SELL reduces cash rather than increasing it — the books will drain to zero on any exit.

3. **No aggregate position limit.** Each BUY is capped at 10% of current cash, but there is no check against total exposure per ticker. If Opportunity Hunter recommends the same ticker on consecutive runs, the book accumulates repeated positions beyond any intended limit.

## Proposed approach

Replace the current in-memory position accounting with a daily-ledger model:

**Schema addition — `virtual_book_nav` table:**
```
(id, book_id, date TEXT, cash REAL, positions_json TEXT,
 total_nav REAL, spy_nav REAL, daily_return REAL, created_at REAL)
```
One row per book per calendar date (or per simulation step).

**Simulator changes:**
- BUY: `fill_price = price × (1 + slippage_pct/100)`; `cash -= qty × fill_price`
- SELL/EXIT: `fill_price = price × (1 - slippage_pct/100)`; `cash += qty × fill_price`; record realized P&L
- Enforce aggregate ticker position limit (e.g., no single ticker > 15% of starting NAV)
- After each fill, write a `virtual_book_nav` row with current cash, positions JSON, market close prices, and total NAV = cash + Σ(qty × mark_price)

**NAV series (stored, not recomputed on read):**
```
NAV_t = Cash_t + Σ_i (Q_i,t × P_i,t)
```
Mark prices come from the same `_get_ticker_price` source used by the outcome labeler; fall back to cost basis only when price fetch fails.

**Nightly job or outcome-labeler hook:**
- After market close, fetch closing prices for all open positions in both books
- Append a `virtual_book_nav` row for that date
- Also fetch SPY close and store alongside

**API:**
- `/api/learning/champion-challenger` reads `virtual_book_nav` for both books rather than recomputing from fills
- Returns a date-indexed NAV series suitable for chart rendering: `[{date, champion_nav, challenger_nav, spy_nav}]`
- All portfolio stats (return, drawdown, turnover, exposure) derived from this table

**Dashboard:**
- Add a label "simulation accounting / experimental" to the portfolio card until this is live
- Once live, render a cumulative-return line chart for champion, challenger, and SPY

## Touches

- `agent_db.py` — `virtual_book_nav` table
- `agents/learning/book_simulator.py` — correct BUY/SELL cash flows and slippage direction; enforce per-ticker limit; write NAV rows
- `agents/learning/outcome_labeler.py` or a new nightly script — mark-to-market all open positions after market close
- `serve.py` — read `virtual_book_nav` instead of recomputing from fills
- `generate_dashboard.py` — cumulative return line chart + "experimental" label until ledger is live
- `tests/test_book_simulator.py` — test SELL increases cash; test slippage direction; test per-ticker aggregate limit

## Done when

- [ ] BUY reduces cash by `qty × price × (1 + slippage)`; SELL increases cash by `qty × price × (1 - slippage)`
- [ ] Open positions are marked to market (closing prices) in NAV computation, not valued at cost basis
- [ ] `virtual_book_nav` table stores one row per book per date with cash, positions JSON, total NAV, SPY NAV, daily return
- [ ] `NAV_t = Cash_t + Σ(Q_i × P_i,t)` computable from stored data for any date range
- [ ] Per-ticker aggregate position limit enforced (configurable, default 15% of starting NAV)
- [ ] Portfolio card in dashboard displays "experimental" label until ledger is live; after go-live shows time-series chart
- [ ] `python -m pytest tests/` passes with no regressions
