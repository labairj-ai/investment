# Pass Trigger Context Through Orchestrator to Agents

- **ID:** 0039
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** 0035

## Problem

`run_agents()` currently accepts a flat `list[str]` of agent type names and creates every `AgentContext` with `trigger_type="orchestrated"`. This loses the per-event context that `detect_triggers()` produces: which ticker triggered the agent, what threshold was crossed, and why. The CC agent specifically branches on `ctx.trigger_type == "cc_eligible"` vs `"cc_mgmt_dte"` to decide whether to propose a new call or manage an existing one — but since the orchestrator always sets `"orchestrated"`, this distinction is always lost. Any future agent that needs to know "why was I called?" has no way to find out.

## Proposed approach

- Change `run_agents()` signature to accept `list[TriggerEvent]` instead of `list[str]`.
- Group events by `agent_type`; pass the list of relevant `TriggerEvent` objects into the `AgentContext` (add a `trigger_events: list[TriggerEvent]` field to `AgentContext`).
- Set `ctx.trigger_type` to the primary trigger type for the agent's events (or a sentinel like `"multi"` if multiple triggers fired for the same agent).
- Update all `run_agents()` call sites in `serve.py` to pass events instead of string lists.
- Update the CC agent to read `ctx.trigger_events` and correctly branch between new-call and management paths.
- Open question: should single-ticker agents receive only their ticker's events, or all events for the agent type? Probably filtered to their ticker.

## Touches

- `agents/orchestrator.py` (`run_agents`, `AgentContext` construction)
- `agents/contracts.py` (`AgentContext` — add `trigger_events` field)
- `agents/covered_call_agent.py` (reads `ctx.trigger_type`)
- `serve.py` (all `run_agents()` call sites)

## Done when

- [ ] `run_agents()` accepts `list[TriggerEvent]` (old `list[str]` signature removed)
- [ ] `AgentContext.trigger_events` is populated with the triggering events for that agent
- [ ] `AgentContext.trigger_type` reflects the actual trigger (not always `"orchestrated"`)
- [ ] CC agent correctly identifies `cc_eligible` vs `cc_mgmt_dte` events from context
- [ ] All call sites updated; no bare string lists passed to `run_agents()`
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change
