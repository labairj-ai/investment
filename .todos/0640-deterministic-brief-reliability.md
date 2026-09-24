# Add Deterministic Brief Reliability Gate

- **ID:** 0640
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0639

## Problem

`_run_briefing_llm()` has an early-return path that emits "Portfolio stable — no material signals today." when there are no attention items and no changes. That decision does not consult `execution_state.status`, `learning_state.status`, `thesis_status`, `freshness.overall`, or `capability_state` error flags. So if the execution-state SQL breaks and is captured as `status="ERROR"`, but no recommendations or attention items exist, the brief can still return "Portfolio stable" — a semantic contradiction. Unknown is not stable.

## Proposed approach

- Before invoking the LLM (or returning the STABLE early-exit), derive a deterministic `brief_health` value: `HEALTHY`, `DEGRADED`, or `ERROR`.
- `HEALTHY`: all required subsystems (`execution_state`, `learning_state`, `thesis_status`, `freshness.overall`, `capability_state`) are AVAILABLE/fresh.
- `DEGRADED`: at least one required subsystem is STALE or UNAVAILABLE.
- `ERROR`: at least one required subsystem is in ERROR.
- The STABLE early-return is only legal when `brief_health == HEALTHY`.
- When `brief_health` is DEGRADED or ERROR, the brief must say so explicitly even if no signals are present: "Cannot confirm portfolio stable — N subsystems degraded/errored."
- Expose `brief_health` in `brief_state` and in the persisted `brief_snapshot_json`.

## Touches

- `portfolio_ai.py` — `build_portfolio_brief_state()` (add `brief_health` derivation), `create_portfolio_brief()` or the briefing-agent call site (gate STABLE on `brief_health == HEALTHY`)
- `agents/briefing_agent.py` — `_run_briefing_llm()` (check `brief_state.get("brief_health")` before STABLE early-return)
- `tests/test_portfolio_brief.py` — test: execution_state ERROR + zero recommendations → brief does NOT contain "stable"; brief_health == ERROR

## Done when

- [ ] `brief_state` contains a `brief_health` key with value `HEALTHY`, `DEGRADED`, or `ERROR`
- [ ] STABLE early-return is blocked when `brief_health != HEALTHY`
- [ ] Test proves: `execution_state.status == ERROR` + zero attention items produces a non-STABLE brief headline
- [ ] `brief_health` is persisted inside `brief_snapshot_json`
