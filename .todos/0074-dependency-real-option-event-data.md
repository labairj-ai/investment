# Implement Real Data for Option/Event/Estimate Dependencies

- **ID:** 0074
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

Three dependency types — `OPTION_LIQUIDITY`, `EVENT_CALENDAR`, `ESTIMATE_REVISION` — are registered stubs that always return no supersession. Additionally, `OPTION_IV` is misnamed: it actually checks option *expiration*, not IV. A recommendation can become stale because IV collapsed or a spread blew out, but the system has no way to detect this. Without real data sources backing these checks, recommendations for options-related actions remain live long after market conditions changed.

## Proposed approach

- Rename `OPTION_IV` → `OPTION_EXPIRATION` in the dependency type registry and the checker function, or add a separate true `OPTION_IV` check using a stored IV snapshot.
- Create a new table `option_quote_snapshots` (ticker, strike, expiration, iv, bid, ask, spread_pct, captured_at) populated when CC recommendations are made and periodically refreshed.
- `_check_option_iv()` (true): compare stored IV to current IV; supersede if IV moved > threshold (e.g., −20%).
- `_check_option_liquidity()`: compare stored spread_pct to current; supersede if spread_pct widened > threshold.
- Create a new table `event_calendar` (ticker, event_type, event_date, confidence, source) for earnings dates, ex-div dates, and other events. Wire `_check_event_calendar()` to supersede when an event has passed or moved inside the recommendation window.
- `_check_estimate_revision()`: pull from `estimate_history` table (to be populated from a data source); supersede if consensus EPS changed > threshold (e.g., −10%).
- Open question: what data source provides IV/spread/estimate revisions? yfinance option chain for IV/spread; earnings estimates may require a paid source.

## Touches

- `agents/dependency_checker.py` — all three stub checkers + rename
- `agent_db.py` — new tables: `option_quote_snapshots`, `event_calendar`, `estimate_history`
- `agents/covered_call_agent.py` — store IV/spread snapshot when recommendation is made
- `tests/test_dependency_checker.py` — real tests for the three previously stubbed types

## Done when

- [ ] `OPTION_IV` checker uses actual IV comparison against a stored snapshot (or renamed to `OPTION_EXPIRATION` with explicit separate `OPTION_IV` stub)
- [ ] `OPTION_LIQUIDITY` checker reads `option_quote_snapshots` and supersedes on wide spread
- [ ] `EVENT_CALENDAR` checker reads `event_calendar` table and supersedes on past/moved events
- [ ] `ESTIMATE_REVISION` checker reads `estimate_history` and supersedes on consensus change
- [ ] All four types have at least one real (non-stub) test
