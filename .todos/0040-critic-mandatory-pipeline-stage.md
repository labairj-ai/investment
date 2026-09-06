# Make Critic a Mandatory Pipeline Stage After Every Producing Agent

- **ID:** 0040
- **Status:** in-progress
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

The Critic agent is listed in `AGENT_ORDER` and has a good deterministic safety gate plus an LLM adversarial pass, but it only runs if `"critic"` is in `triggered_agents`. This means any call to `run_agents(snapshot, ["opportunity_hunter"])` skips Critic entirely. The Saturday sweep calls agents directly and never routes through Critic at all. The manual candidate workflow has the same gap. Recommendations from any agent can reach the Decision Queue without Critic review, which defeats the purpose of having a Critic.

## Proposed approach

- After all non-Critic producing agents finish in `run_agents()`, automatically run Critic on their output — do not require callers to include `"critic"` in the agent list.
- Critic should receive the list of `Recommendation` objects produced in the current run as its input, not a new portfolio snapshot pass.
- Persist recommendations as "provisional" before Critic; update to "reviewed" + adjust confidence after Critic passes.
- Define the architectural rule: Critic is a pipeline stage, not a peer. Never add `"critic"` to a trigger event; it runs automatically.
- Alternative: make `run_agents()` always append Critic at the end if any actionable recommendations were produced (actions other than `NO_ACTION` / `HOLD`).
- Open question: should HOLD recommendations also go through Critic, or only REVIEW/TRIM/EXIT/BUY?

## Touches

- `agents/orchestrator.py` (`run_agents` post-loop logic)
- `agents/critic_agent.py` (may need to accept a rec list instead of re-scanning DB)
- `agent_db.py` (provisional → reviewed status transition)

## Done when

- [ ] Calling `run_agents(snapshot, ["opportunity_hunter"])` automatically runs Critic on the result
- [ ] No recommendation with action TRIM/EXIT/BUY can reach status `"open"` without a Critic review row
- [ ] Saturday sweep recommendations show Critic review records in the DB
- [ ] `"critic"` does not appear in any `TriggerEvent.agent_type`
- [ ] Critic veto (REJECT) prevents a recommendation from appearing in the Decision Queue
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change
