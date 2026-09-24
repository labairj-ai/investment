# Make All Failure Defaults Fail Closed

- **ID:** 0645
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0644

## Problem

Several default values in the brief pipeline assume health when the relevant data is absent:

1. `brief_health = brief_state.get("brief_health", "HEALTHY")` — if `brief_health` is missing (schema regression, test fixture, partial caller), the system assumes healthy and the STABLE gate silently passes. Absence of proof of health is not proof of health.
2. `portfolio_state = briefing_output.get("portfolio_state", "STABLE")` — if the LLM returns a dict without `portfolio_state`, the default is `STABLE`. Should be `UNKNOWN`.
3. `briefing_output = {"portfolio_state": "STABLE", ...}` in the top-level exception handler of `run_briefing_agent()` — brief generation failure should never claim stability.

These are all fail-open defaults in a system that is explicitly designed to fail closed.

## Proposed approach

- Change `brief_state.get("brief_health", "HEALTHY")` → `brief_state.get("brief_health", "UNKNOWN")` everywhere in `agents/briefing_agent.py`. Alternatively, treat absence as `ERROR`:
  ```python
  if "brief_health" not in brief_state:
      brief_health = "ERROR"
  ```
- Change `briefing_output.get("portfolio_state", "STABLE")` → `briefing_output.get("portfolio_state", "UNKNOWN")` everywhere in `portfolio_ai.py` and `serve.py`.
- In `run_briefing_agent()` exception handler: change `"portfolio_state": "STABLE"` → `"portfolio_state": "UNKNOWN"`.
- Audit for any other `"STABLE"` literal defaults in the brief pipeline.

## Touches

- `agents/briefing_agent.py` — `_run_briefing_llm()`, `run_briefing_agent()` exception handler
- `portfolio_ai.py` — any `.get("portfolio_state", "STABLE")` call sites
- `serve.py` — any `.get("portfolio_state", "STABLE")` call sites
- `tests/test_portfolio_brief.py` — test that missing `brief_health` key is treated as ERROR/UNKNOWN, not HEALTHY

## Done when

- [ ] No code path uses `"HEALTHY"` as the default for a missing `brief_health`
- [ ] No code path defaults a missing `portfolio_state` to `"STABLE"`
- [ ] Exception handler in `run_briefing_agent()` produces `"UNKNOWN"` not `"STABLE"`
- [ ] Test: `brief_state` with no `brief_health` key → brief_health treated as ERROR/UNKNOWN, STABLE blocked
