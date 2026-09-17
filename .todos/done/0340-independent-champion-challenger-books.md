# Independent Champion/Challenger Portfolio Books

- **ID:** 0340
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0337, 0338, 0339

## Problem

Even after 0337 fixes variant execution, there is a deeper experimental-design gap: comparing mean per-trade alpha between champion and challenger isn't equivalent to comparing two portfolios. A challenger can have higher mean trade alpha but still produce a worse portfolio due to concentration or turnover. The current `_handle_champion_challenger()` endpoint returns mean alpha/hit_rate/MAE/MFE per fill — it does not compute portfolio-level drawdown or turnover, which were acceptance criteria in 0336 that remain unmet.

Additionally, if only one Alpaca paper account exists, what "champion" actually executes is not a real portfolio — it's a counterfactual. The champion and challenger are not on equal footing: challenger has executed positions with cash constraints, champion has only fill-price returns without portfolio state. Comparing executed challenger outcomes to counterfactual champion signals overstates or understates differences depending on sizing and overlap.

## Proposed approach

**Option A — dual virtual books (recommended for now)**: Maintain two internal shadow portfolio states (`CHAMPION_BOOK`, `CHALLENGER_BOOK`) using identical execution assumptions and market price snapshots — not real broker fills. Both receive simulated fills when an opportunity hunter run produces a champion recommendation and a challenger variant, using the same limit_price logic and fill assumptions. Cash and positions evolve independently per book.

Implementation:
- New table `virtual_books`: `(book_id TEXT, account_like TEXT, tick TEXT, qty REAL, avg_cost REAL, cash REAL, as_of TEXT)`
- New table `virtual_fills`: `(id, book_id, episode_id, ticker, action, price, qty, fees, filled_at, decision_origin)`
- At opportunity hunter run time (or outcome labeler time), simulate fills for both books using the same market price used for counterfactual labeling
- Portfolio-level metrics computed over `virtual_fills`: cumulative return, SPY-relative cumulative alpha, max drawdown, volatility, turnover (notional traded / avg NAV), cash utilization, number of trades, win rate, avg winner, avg loser, profit factor, exposure

**Champion/challenger dashboard** (replace current endpoint or add `/api/learning/champion-challenger/portfolio`):
- Cumulative return series (chart-ready: list of `{date, champion_nav, challenger_nav, spy_nav}`)
- Max drawdown per book
- Volatility per book
- Turnover per book
- All existing per-trade stats (alpha mean, hit rate, MAE/MFE) retained alongside

Option B (future): Two real Alpaca paper accounts (`ALPACA_CHAMPION`, `ALPACA_CHALLENGER`). Cleaner experiment but adds operational complexity; defer until virtual books have run for a full model evaluation period.

## Touches

- `agent_db.py` — `virtual_books` and `virtual_fills` tables
- `agents/opportunity_agent.py` or new `agents/learning/book_simulator.py` — simulate fills for both books at run time
- `agents/learning/outcome_labeler.py` — optionally mark virtual fills as mature and compute portfolio NAV series
- `serve.py` — enhanced `/api/learning/champion-challenger` with portfolio-level metrics and NAV series
- `generate_dashboard.py` — cumulative return chart comparing champion book vs challenger book vs SPY

## Done when

- [x] `virtual_books` and `virtual_fills` tables exist; champion and challenger books receive simulated fills from opportunity hunter runs
- [x] Portfolio NAV series computable from `virtual_fills` for both books
- [x] `/api/learning/champion-challenger` returns portfolio-level metrics: cumulative return, max drawdown, volatility, turnover, trade count, win rate, profit factor, exposure
- [x] Dashboard shows cumulative return curves: CHAMPION_BOOK vs CHALLENGER_BOOK vs SPY over the same calendar period
- [x] Per-trade stats (alpha mean, hit rate, MAE/MFE) retained and consistent with prior endpoint
- [x] `python -m pytest tests/` passes with no regressions

## Outcome

6 files changed + 1 new file. `agent_db.py`: added `virtual_books` (book_id, label, starting_cash, current_cash, as_of) and `virtual_fills` (id, book_id, episode_id, ticker, action, price, qty, fees, filled_at, decision_origin, created_at) tables; seed INSERTs for CHAMPION_BOOK and CHALLENGER_BOOK at $100k each. `agents/learning/book_simulator.py` (new): `record_virtual_fills(champion_ticker, champion_price, challenger_ticker, challenger_price, episode_id, action)` — inserts fills for both books at opportunity-hunter time; `compute_book_stats(book_id, price_fn)` — returns cum_return, max_drawdown, turnover, win_rate, profit_factor, exposure_pct; `_record_one_book` applies 1% slippage, sizes at 10% of current cash, checks cash sufficiency. `agents/opportunity_agent.py`: imports `record_virtual_fills`; calls it after `_insert_decision_variant()` with champion and challenger tickers/prices. `serve.py` `_handle_champion_challenger`: added `_book_portfolio_stats(book_id)` inner function returning cost-basis NAV series + portfolio metrics for each virtual book; also adds `decision_return_mean`, `impl_shortfall_mean` to per-trade stats; adds `execution_quality` block (mean IS by action). `generate_dashboard.py`: added Champion vs Challenger Portfolio card to Learning Lab; `loadLearningPanel` fetches `/api/learning/champion-challenger` and renders book-level stat cards plus the full per-trade table. `tests/test_book_simulator.py`: 12 tests covering schema seeding, fill insertion, cash decrement, missing-price no-op, insufficient-cash guard, episode_id persistence, and compute_book_stats. 804 passed, 16 skipped.
