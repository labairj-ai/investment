# Expand Recommendation Dependency Types Beyond PRICE and THESIS_VERSION

- **ID:** 0049
- **Status:** backlog
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

- [ ] At least 3 new dependency types implemented with checkers
- [ ] CC recommendations include OPTION_IV dependency; superseded when IV moves >20%
- [ ] Sell recommendations include POSITION_WEIGHT dependency; superseded when weight changes >2pp
- [ ] `check_all_dependencies()` handles all new types without error
- [ ] Tested: manually alter a macro score and confirm relevant Guardian rec is superseded
