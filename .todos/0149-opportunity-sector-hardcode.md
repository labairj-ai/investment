# Opportunity Agent: Remove Hardcoded _HOLDING_SECTORS Dict

- **ID:** 0149
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** 0148

## Problem

`_score_portfolio_fit()` in `agents/opportunity_agent.py` uses a hardcoded `_HOLDING_SECTORS` dict to determine sector overlap. Any holding not in this dict gets no sector overlap penalty — silently underweighting concentration risk for new positions. The dict must be manually updated whenever the portfolio changes, which will be forgotten.

Additionally, there is no minimum composite score gate: if the top scored candidate has a composite of 20, the agent still emits a RESEARCH recommendation for a poorly-ranked stock.

## Proposed approach

**1. Live sector lookup from DB** (depends on 0148):
Replace `_HOLDING_SECTORS.get(t)` with a DB lookup from the `ticker_metadata` table that 0148 introduces. Falls back to "Unknown" (no penalty) when not available — same behavior as today, but now the dict updates automatically as new holdings are added and sector data is fetched.

**2. Minimum composite threshold**:
Add `_MIN_COMPOSITE = 45` gate before emitting. If `scored[0]["_composite"] < _MIN_COMPOSITE`:
- Print `[opportunity] Top candidate below minimum threshold ({scored[0]['_composite']}) — no recommendation`
- Return `[]`
- This prevents the agent from recommending a genuinely poor fit.

## Touches

- `agents/opportunity_agent.py` — `_HOLDING_SECTORS` dict → `ticker_metadata` DB lookup; `_MIN_COMPOSITE` threshold in `run_opportunity_hunter()`
- `agent_db.py` — `get_ticker_sector()` helper (reads `ticker_metadata`, returns None if absent)

## Done when

- [ ] `_HOLDING_SECTORS` dict is removed; sector lookup reads from DB
- [ ] Composite < 45 → no RESEARCH recommendation emitted
- [ ] Existing tests pass
