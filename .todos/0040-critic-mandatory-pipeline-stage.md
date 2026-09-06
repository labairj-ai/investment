# Make Critic a Mandatory Pipeline Stage After Every Producing Agent

- **ID:** 0040
- **Status:** done
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

- [x] Calling `run_agents(snapshot, ["opportunity_hunter"])` automatically runs Critic on the result
- [x] No recommendation with action TRIM/EXIT/BUY can reach status `"open"` without a Critic review row
- [x] Saturday sweep recommendations show Critic review records in the DB
- [x] `"critic"` does not appear in any `TriggerEvent.agent_type`
- [x] Critic veto (REJECT) prevents a recommendation from appearing in the Decision Queue
- [x] **Backend QA:** deployed to optiplex, service running clean
- [x] **Frontend QA:** recommendations API returns data, no errors
- [x] **No service regression:** investment service active and healthy

## Outcome

`AGENT_ORDER` now contains only producers; `_PIPELINE_STAGES = ["critic", "briefing"]` is separate. `run_agents()` strips critic/briefing from `triggered_agents`, runs producers, then auto-runs Critic if any unreviewed open recs exist in the DB. Briefing still fires via `detect_triggers()` and runs as the final stage. Extracted `_run_single_agent()` to eliminate duplicated boilerplate. No changes to `critic_agent.py` or `agent_db.py` — Critic already queries unreviewed recs from DB, so it naturally picks up whatever producers just wrote.

Next: 0044 (Fix Dep Re-eval to Route Through Critic Pipeline) and 0047 (Build Briefing Agent) are now unblocked.
