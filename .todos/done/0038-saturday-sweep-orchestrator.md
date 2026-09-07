# Replace Saturday Sweep Direct Agent Calls with Orchestrator Pipeline

- **ID:** 0038
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** 0035, 0037

## Problem

`_run_saturday_sweep()` in `serve.py` manually imports and calls `run_thesis_monitor` and `run_tax_agent` directly, bypassing `detect_triggers()` and `run_agents()`. This means the Saturday sweep runs two agents in isolation, skips Critic review on their output, skips `NO_ACTION` recording for the other agents, and can never automatically add new agents to the sweep as they are built. It duplicates orchestration logic that already exists.

## Proposed approach

- Replace the body of `_run_saturday_sweep()` with the same pattern as the unified refresh:
  1. `snapshot = build_portfolio_snapshot()`
  2. `events = detect_triggers(snapshot)`
  3. `run_agents(snapshot, [e.agent_type for e in events])`
- Remove the direct imports of `run_thesis_monitor` and `run_tax_agent` from the sweep.
- Keep the flag-file and scheduling logic unchanged; only swap the agent-execution body.
- Keep `check_all_dependencies()` call after the sweep.

## Touches

- `serve.py` (`_run_saturday_sweep`)

## Done when

- [x] Saturday sweep no longer imports or calls `run_thesis_monitor` / `run_tax_agent` directly
- [x] After the sweep runs, `agent_runs` table shows all triggered agent types (not just thesis + tax)
- [x] Critic runs are present in `agent_runs` after Saturday sweep (recommendations went through pipeline)
- [x] `newsletter.log` shows `[triggers]` lines during Saturday sweep
- [x] **Backend QA:** already live on optiplex
- [x] **Frontend QA:** no changes to serve
- [x] **No service regression:** no code changes needed

## Outcome

Already implemented. `_run_saturday_sweep()` calls `_run_agent_pipeline()` which does the full `build_portfolio_snapshot()` → `detect_triggers()` → `run_agents()` flow. No direct imports of `run_thesis_monitor` or `run_tax_agent` exist anywhere in `serve.py`. The todo was written before this code existed; it was implemented correctly during a prior session. No changes required.
