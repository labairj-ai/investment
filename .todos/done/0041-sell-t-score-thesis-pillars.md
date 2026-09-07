# Fix Sell/Trim T-Score to Use thesis_pillars Instead of thesis_claims

- **ID:** 0041
- **Status:** done
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

- [x] `_score_T()` queries `thesis_pillars`, not `thesis_claims`
- [x] T-score for a ticker matches the health score the Thesis Monitor would report for the same ticker
- [x] Critical pillar violation produces T ≥ 90 in the sell score
- [x] No `thesis_claims` query remains in the primary path of `sell_trim_agent.py`
- [x] Manually verified on live optiplex DB: BP composite=78.5→T=22, BRK-B composite=53→T=47, BTC composite=50→T=50
- [x] **Backend QA:** deployed to optiplex, service running clean
- [x] **Frontend QA:** no dashboard changes; service healthy
- [x] **No service regression:** investment service active

## Outcome

Replaced `_score_T()` body to read `thesis_pillars` joined to `investment_theses`. Composite = Σ(importance × stored_score) / Σ(importance), using `_PILLAR_STATUS_SCORE` map as fallback when `score` is NULL. T = round(100 − composite), then floor rules: critical VIOLATED → T≥90; 2+ VIOLATED → T≥75; WARNING-only (no violations) → T≤50. Legacy `thesis_claims` path kept as fallback for tickers with no pillar rows. T-score now matches what the Thesis Monitor's composite health would report for the same ticker.
