# Build Opportunity Hunter Agent (Phase 6)

- **ID:** 0014
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005, 0006, 0007, 0013

## Problem

The Buffett screener finds high-quality stocks but has no concept of portfolio fit. A great stock that's redundant with three existing holdings, or that would push an already-overweight layer further over target, should rank lower than an equally good stock that fills a gap. Currently there is no agent that bridges the screener output to the actual portfolio state and answers "which of these would actually improve my portfolio?"

## Proposed approach

`agents/opportunity_agent.py`

Triggered by: new Buffett screener winner; layer weight < (target - 5pp) for > 3 days.

**Opportunity score formula (all deterministic except portfolio fit):**
`Score = 0.30*Q + 0.25*V + 0.20*PF + 0.15*C + 0.10*EC`

- **Q — Quality** (from Buffett screener's existing composite quality score)
- **V — Valuation** (from Buffett screener's valuation metrics)
- **PF — Portfolio Fit**: layer deficit bonus if the candidate fills an underweight layer; correlation penalty if candidate overlaps ≥ 2 existing holdings in same sector/factor; concentration penalty if adding it would push any position > `max_single_position_pct`
- **C — Catalyst/Setup**: upcoming catalyst (earnings, spin-off, analyst coverage initiation); technical setup if tracked
- **EC — Evidence Confidence**: from `confidence.py`, based on freshness and completeness of fundamental data

**LLM role** (narrow):
Receives top 3 candidates by score + current portfolio context. Answers which of the 3 best improves the portfolio and why — does not generate the score, does not produce financial values, does not search for new candidates.

Output:
```json
{
  "action": "RESEARCH",
  "ticker": "CANDIDATE",
  "why": "...",
  "portfolio_rationale": "...",
  "main_risk": "...",
  "no_action_case": "..."
}
```

`RESEARCH` not `BUY` — agent surfaces opportunities, user decides.

## Touches

`agents/opportunity_agent.py` (new), `buffett_screener.py` (read winners from buffett.db), `agents/orchestrator.py`, `portfolio_ai.py` (correlation/overlap check)

## Done when

- [ ] Portfolio Fit (PF) score penalizes redundant candidates and rewards layer gap fills
- [ ] LLM receives ≤ 3 candidates — not the full screener universe
- [ ] Output action is `RESEARCH`, not `BUY`
- [ ] Recommendation includes which layer the candidate would fill and current layer deficit
- [ ] Agent handles case where no Buffett screener winners exist (no recommendation, no LLM call)
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced

