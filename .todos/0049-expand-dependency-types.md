# Expand Recommendation Dependency Types Beyond PRICE and THESIS_VERSION

- **ID:** 0049
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

`dependency_checker.py` handles only two dependency types: `PRICE` (stock moved beyond tolerance) and `THESIS_VERSION` (thesis updated). The original design envisioned a much richer set relevant to different agent types. A CC recommendation should expire if IV changes materially or an earnings event is imminent — not just if the price moves. A macro-driven Guardian alert should expire if macro scores change. A tax recommendation should expire if the lot crosses the LT boundary. Currently these recommendations stay "open" indefinitely even when their premise has evaporated.

## Proposed approach

Add checkers for (at minimum):
- `OPTION_IV`: option implied volatility changed more than X% — invalidates CC recommendations
- `OPTION_QUOTE`: option premium changed more than X% — invalidates CC recommendations
- `EARNINGS_RELEASE`: earnings date passed or moved — invalidates CC and some sell recs
- `MACRO_STATE`: macro score dimension changed by threshold — invalidates macro-driven Guardian recs
- `POSITION_WEIGHT`: portfolio weight changed by threshold — invalidates concentration-based sell recs
- `FINANCIAL_PERIOD`: new quarterly financials released — invalidates fundamental-based recs

Each new type needs:
1. A checker function in `dependency_checker.py`
2. Agent code that writes `Dependency` objects with the new type when producing recommendations
3. DB data source for the checker (price DB, macro scores table, financials table, etc.)

## Touches

- `agents/dependency_checker.py` (new checker functions, dispatch in `check_all_dependencies`)
- `agents/covered_call_agent.py` (write OPTION_IV, EARNINGS_RELEASE dependencies)
- `agents/sell_trim_agent.py` (write POSITION_WEIGHT, FINANCIAL_PERIOD dependencies)
- `agents/portfolio_guardian.py` (write MACRO_STATE dependencies)
- `agent_db.py` (any schema needed for storing new dependency metadata)

## Done when

- [x] At least 3 new dependency types implemented with checkers: POSITION_WEIGHT, MACRO_STATE, FINANCIAL_PERIOD
- [x] CC recommendations include MACRO_STATE dependency (OPTION_IV skipped — no live IV data in DB; MACRO_STATE is the next-best CC invalidator)
- [x] Sell recommendations include POSITION_WEIGHT dependency; superseded when weight changes >2pp
- [x] `check_all_dependencies()` handles all new types without error (fetches weights/macro/periods once, dispatches by type)
- [ ] Tested: manually alter a macro score and confirm relevant CC rec is superseded
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change

## Outcome

Four files changed:

- **`agents/dependency_checker.py`**: Added `_latest_weights()`, `_latest_macro_scores()`, `_latest_financial_periods()` data helpers; added `_check_position_weight()`, `_check_macro_state()`, `_check_financial_period()` checkers; `check_all_dependencies()` now fetches all three data sets once and dispatches all 5 types.
- **`agents/sell_trim_agent.py`**: TRIM/EXIT/HOLD recs now include `POSITION_WEIGHT` dependency (2pp tolerance on current weight_pct).
- **`agents/covered_call_agent.py`**: SELL_CC recs now include `MACRO_STATE` dependency when macro scores exist for the ticker (15-point threshold on any dimension); OPTION_IV skipped — no live IV in DB.
- **`agents/opportunity_agent.py`**: RESEARCH recs now include `FINANCIAL_PERIOD` dependency — superseded when a newer quarterly period_end appears in company_financials.
