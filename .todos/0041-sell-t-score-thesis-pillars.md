# Fix Sell/Trim T-Score to Use thesis_pillars Instead of thesis_claims

- **ID:** 0041
- **Status:** in-progress
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

The Sell/Trim agent's T-score (`_score_T()`) — which carries 40% of `SellStrength` — queries `thesis_claims` and checks for `current_status IN ('violated', 'weakened')`. But the modern thesis system (built in 0030–0033) operates on `thesis_pillars` and `thesis_metrics`, not `thesis_claims`. The Thesis Monitor works from `thesis_pillars`. This creates two parallel, divergent interpretations of thesis health: the Thesis Monitor sees one picture, the Sell/Trim agent sees another. A ticker could show a healthy thesis in the monitor and a broken thesis in the sell score simultaneously, because they read different tables.

## Proposed approach

- Replace `_score_T()` body to read from `thesis_pillars` (joined to `investment_theses`) instead of `thesis_claims`.
- Compute T using pillar status + importance + critical flag + persistence, mirroring what the Thesis Monitor already calculates:
  - Base: `T = 100 - thesis_health_score` (reuse or import the health calculation from `thesis_agent.py`)
  - Critical pillar VIOLATED → floor T at 90
  - 2+ pillars VIOLATED → floor T at 75
  - Pillar WARNING only → cap T at 50
- If `thesis_claims` table still exists for legacy data, fall back to it only if no `thesis_pillars` rows are found for the ticker.
- Export or extract the thesis-health calculation from `thesis_agent.py` so both agents share one implementation.

## Touches

- `agents/sell_trim_agent.py` (`_score_T()`)
- `agents/thesis_agent.py` (extract shared health-score function)

## Done when

- [ ] `_score_T()` queries `thesis_pillars`, not `thesis_claims`
- [ ] T-score for a ticker matches the health score the Thesis Monitor would report for the same ticker
- [ ] Critical pillar violation produces T ≥ 90 in the sell score
- [ ] No `thesis_claims` query remains in `sell_trim_agent.py`
- [ ] Existing tests (if any) updated; manually verify on a ticker with a known pillar violation
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change
