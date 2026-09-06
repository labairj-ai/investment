# Fix Dependency Re-evaluation to Route Through Critic Pipeline

- **ID:** 0044
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0040

## Problem

`_trigger_reeval()` in `dependency_checker.py` calls the agent handler directly via `orch._registry.get(agent_type)`, then inserts the resulting recommendations straight into the DB. This bypasses the orchestrator, Critic, confidence adjustment, and all post-processing. A re-evaluated sell recommendation from a superseded CC rec can land in the Decision Queue without any Critic review — the same gap that 0040 closes for normal runs must also be closed for re-evaluations.

## Proposed approach

- Replace the direct `handler(ctx)` + manual `insert_recommendation()` loop in `_trigger_reeval()` with a call to `run_agents(snapshot, [triggering_event])` (after 0039 changes the signature to accept events).
- Construct a synthetic `TriggerEvent` for the re-eval with `trigger_type="dep_superseded"`, the original ticker, and the agent type.
- This way the re-eval path is identical to the normal path: agent → Critic → persist → Decision Queue.
- Remove the manual `insert_recommendation()` and `finish_agent_run()` calls from `_trigger_reeval()` since `run_agents()` handles those.

## Touches

- `agents/dependency_checker.py` (`_trigger_reeval`)

## Done when

- [x] `_trigger_reeval()` calls `run_agents()` rather than invoking the handler directly
- [x] Re-evaluated recommendations have Critic review records in the DB
- [x] No `orch._registry.get()` direct-call pattern remains in `dependency_checker.py`
- [x] Manual `insert_recommendation()` removed from `_trigger_reeval()`
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change

## Outcome

One file changed: `agents/dependency_checker.py` — `_trigger_reeval()` replaced with a call to `run_agents(snapshot, [TriggerEvent(trigger_type="dep_superseded", ...)])`. The new implementation builds a full `PortfolioSnapshot` via `build_portfolio_snapshot()`, wraps the ticker+agent_type in a `TriggerEvent`, and calls the standard `run_agents()` path — so re-evaluated recs go through Critic and full persistence just like normal pipeline runs. No `orch._registry` direct-call pattern remains.
