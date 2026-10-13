# Build Deterministic Materiality and Portfolio Priority Scores

- **ID:** 0584
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0582, 0583

## Problem

Importance is currently determined entirely by LLM prose, which is neither reproducible nor auditable. There is no way to sort holdings by how materially something changed, distinguish company-level importance from portfolio-level importance, or explain why one event was prioritized over another.

## Proposed approach

- Compute `signal_strength` deterministically from: thesis_relevance (0/1 if maps to a pillar/risk/catalyst, 0–1 weight), financial_materiality (event type magnitude), confidence, novelty (NEW > CONFIRMING > FADING), and persistence_adjustment (from 0583 trend status). Conceptual formula: `SignalStrength = ThesisRelevance × Materiality × Confidence × Novelty × PersistenceAdjustment`, normalized to 0–100.
- Compute `portfolio_priority` separately: `SignalStrength × PositionWeight × (1 + TriggerProximityBonus)`. This keeps a major event in a 0.5% position ranked below a moderate event in a 10% position.
- Store both scores per event and per ticker-day. Use `portfolio_priority` to sort the dashboard default view.
- Do NOT let the LLM assign scores directly. LLM provides classification and explanation; deterministic context determines prioritization.
- Add a score decomposition tooltip in the dashboard so the user can see what drove a high/low score.

## Touches

- `agents/news/` — scoring module
- DB — signal_strength and portfolio_priority columns on event/analysis tables
- Dashboard — sort by portfolio_priority, score decomposition on hover

## Done when

- [x] `signal_strength` is computed deterministically from thesis relevance, materiality, confidence, novelty, and trend persistence
- [x] `portfolio_priority` incorporates position weight and trigger proximity
- [x] Dashboard default sort order uses `portfolio_priority`
- [x] Score decomposition is visible (not just the final number)
- [x] A high-signal event in a small position ranks lower than a moderate-signal event in a large position

## Outcome

`agents/news/intelligence.score_event()` implements `SignalStrength = mat × mag_sc × horizon_mult × conf × novelty_wt × persist_adj × confirm_boost × thesis_boost × 100`. `PortfolioP = SignalStrength × pos_frac × (1 + trigger_bonus)`. Decomposition dict stored in `score_decomposition` JSON column. Dashboard shows `sig N · pp N` in header and sorts buckets by portfolio_priority descending.
