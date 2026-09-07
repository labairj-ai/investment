# Build Canonical build_portfolio_snapshot() Function

- **ID:** 0037
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

Every entry point that needs a `PortfolioSnapshot` builds its own partial version: the Saturday sweep constructs one with `shares=0, avg_cost=0, market_value=0, weight_pct=0`; the dependency re-evaluator does the same. These partial snapshots are dangerous — any agent that reads `weight_pct` or `market_value` for a sell/trim or CC decision gets zeros. There is no single authoritative function that reads all required fields from the live DB and CSV.

## Proposed approach

- Create `build_portfolio_snapshot()` in a shared location (candidate: `agents/snapshot.py` or `portfolio_ai.py`).
- It should read from: `holdings.csv` (tickers, layer, shares, avg_cost), `holding_day` table (current price, today's change), `cost_lots` (for tax context), layer weight history, and macro scores.
- Return a fully-populated `PortfolioSnapshot` with no zero-filled fields for live holdings.
- Replace every existing snapshot construction site with a call to this function: `_run_daily()`, `_run_saturday_sweep()`, `_trigger_reeval()` in dependency_checker, and any manual API path that currently assembles its own snapshot.
- Open question: should this function accept a `date` param for historical re-evaluation?

## Touches

- New file: `agents/snapshot.py` (or addition to `portfolio_ai.py`)
- `serve.py` (`_run_saturday_sweep`, `_run_daily`, manual candidate path)
- `agents/dependency_checker.py` (`_trigger_reeval`)

## Done when

- [x] Single `build_portfolio_snapshot()` function exists and is importable
- [x] Returned snapshot has non-zero `shares`, `avg_cost`, `market_value`, `weight_pct` for all held positions
- [x] `_trigger_reeval()` uses it — no more `shares=0` snapshots during re-eval
- [x] Saturday sweep uses it — no more manually-assembled partial snapshots
- [x] Unit-testable: can be called in isolation and returns a valid `PortfolioSnapshot`
- [x] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [x] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [x] **No service regression:** investment service still running; all existing API routes respond correctly after the change

## Outcome

Created `agents/snapshot.py` with the canonical `build_portfolio_snapshot()` extracted from `serve.py`. `serve.py`'s wrapper now delegates to it (2 lines). Replaced 3 partial-snapshot construction sites: `dependency_checker._trigger_reeval` (was shares=0/avg_cost=0), `serve.py` opportunity hunter (was empty PortfolioSnapshot), and `serve.py` manual agent trigger (was wrong current_price = value/shares). Removed ~80 lines of duplicated DB/CSV reading code. Deployed to optiplex; service healthy, recommendations API confirmed returning data.
