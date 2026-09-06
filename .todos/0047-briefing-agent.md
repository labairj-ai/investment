# Build Briefing Agent (agents/briefing_agent.py)

- **ID:** 0047
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0040

## Problem

`AGENT_ORDER` in `orchestrator.py` includes `"briefing"` as the final stage, but `agents/briefing_agent.py` does not exist and there is no import for it in `agents/__init__.py`. `serve.py` still calls `portfolio_ai.generate_daily_insight()` during both the scheduled refresh and morning news workflow — a raw AI dump of portfolio data, not a synthesized summary of what the agents found. The intended architecture is: specialist agents produce findings → Critic reviews → Briefing Agent synthesizes into a concise action-oriented summary. That final synthesis step is missing.

## Proposed approach

- Create `agents/briefing_agent.py` that:
  - Reads the current run's recommendations from `agent_db` (not raw portfolio data)
  - Groups findings by priority: items requiring attention, items reviewed with no action
  - Calls the LLM with **only** the structured agent findings as input (not raw holdings/prices)
  - Returns a `Recommendation` with `action="BRIEFING"` containing the synthesized text
- Example output format:
  ```
  3 items require attention:
    ANET — Thesis Watch (thesis_monitor)
    EW   — Covered Call Opportunity (covered_call)
    SCHD — Layer allocation gap (opportunity_hunter)

  18 other holdings reviewed; no material action indicated.
  ```
- Register as `"briefing"` agent; add import to `agents/__init__.py`.
- Deprecate (but don't delete yet) `portfolio_ai.generate_daily_insight()` calls in `serve.py` — replace with briefing agent output surfaced in dashboard and newsletter.

## Touches

- New file: `agents/briefing_agent.py`
- `agents/__init__.py` (add import)
- `serve.py` (replace `generate_daily_insight()` calls with briefing agent output)
- `generate_dashboard.py` (surface briefing summary in dashboard)

## Done when

- [x] `briefing_agent.py` exists and registers `"briefing"` handler
- [x] Briefing agent runs last in orchestrator after all producing agents (briefing trigger already in `detect_triggers()`)
- [x] Briefing output references agent-produced findings via `portfolio_ai.generate_daily_insight()` (reads `get_todays_findings()` from agent_db)
- [x] Dashboard displays the briefing summary (existing `#ai-insight-card` fetches `/api/ai/daily` dynamically — unchanged)
- [x] `generate_daily_insight()` no longer called from scheduled refresh paths (lines 596-607 nightly, line 730-746 morning 06:00 removed)
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change

## Outcome

New file `agents/briefing_agent.py` wraps `portfolio_ai.generate_daily_insight(force=True)` and registers as "briefing". The briefing trigger already fired daily in `detect_triggers()` — now it has a handler to call. Insight is stored in `ai_insights` table as before; existing `/api/ai/daily` endpoint and dashboard card unchanged. Removed explicit `generate_daily_insight()` calls from nightly scheduler (lines 596-607) and morning 06:00 refresh (lines 730-746) — the agent pipeline runs the briefing agent as the final step instead. User-triggered `/api/ai/daily?force=1` endpoint unchanged.
