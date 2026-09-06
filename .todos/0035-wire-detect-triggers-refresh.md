# Wire detect_triggers into Every Portfolio Refresh

- **ID:** 0035
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

`detect_triggers()` and `run_agents()` exist and are fully implemented, but `serve.py` never calls them during scheduled or on-demand price refreshes. The scheduler still runs the old workflow (refresh data → generate AI insight → generate dashboard → check dependencies). The Saturday sweep calls `run_thesis_monitor` and `run_tax_agent` directly rather than routing through `detect_triggers()` → `run_agents()`. The agent system has a brain and sensory system but no nervous connection between them.

## Proposed approach

- Create a single `build_portfolio_snapshot()` helper in `serve.py` (or a shared module) that reads live prices, lots, layer weights, and macro scores into a fully-populated `PortfolioSnapshot`.
- After every price refresh (both the morning run in `_run_daily()` and the 5 PM refresh path), call:
  1. `snapshot = build_portfolio_snapshot()`
  2. `events = detect_triggers(snapshot)`
  3. `triggered_agents = list({e.agent_type for e in events})`
  4. `run_agents(snapshot, triggered_agents)`
- Replace the Saturday sweep's direct `run_thesis_monitor` / `run_tax_agent` calls with this same pipeline.
- Open question: should `build_portfolio_snapshot()` live in `serve.py`, `portfolio_ai.py`, or a new `agents/snapshot.py`? Centralise it so dependency checker and dep re-eval can also use it (see 0010).

## Touches

- `serve.py` (`_run_daily`, 5 PM refresh block, `_run_saturday_sweep`)
- `agents/contracts.py` (verify `PortfolioSnapshot` fields are complete)
- Possibly new `agents/snapshot.py` or addition to `portfolio_ai.py`

## Done when

- [ ] After a manual `/api/refresh` call, `agent_runs` rows appear in `investment.db` for at least one agent type
- [ ] `NO_ACTION` rows are logged for holdings that don't cross any threshold
- [ ] Saturday sweep no longer calls `run_thesis_monitor` / `run_tax_agent` directly
- [ ] `newsletter.log` on optiplex shows `[triggers]` and `[Orchestrator]` lines after each scheduled refresh
- [ ] No partial `PortfolioSnapshot` (shares=0, market_value=0) reaches any agent during a scheduled run
