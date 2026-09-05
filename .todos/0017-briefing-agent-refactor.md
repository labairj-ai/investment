# Refactor Daily Briefing Agent to Consume Specialist Findings

- **ID:** 0017
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0010, 0011, 0012, 0013, 0014, 0015

## Problem

The current `generate_daily_insight()` passes the model a massive combined prompt: holdings, prices, layers, macro, lots, realized gains, behavior patterns, macro scores, and news findings. This pushes against the model's context budget, requires compaction hacks, and produces a generalist summary that lacks the depth of specialist analysis. Once specialist agents exist, the briefing agent should receive their distilled findings — not raw portfolio data. This both improves quality and dramatically reduces token usage.

## Proposed approach

Rewrite the briefing agent to be a synthesis layer, not a research layer.

**Input** (structured, not prose):
```json
{
  "guardian_findings": [...],
  "cc_findings": [...],
  "thesis_findings": [...],
  "opportunity_findings": [...],
  "tax_findings": [...],
  "critic_reviews": [...],
  "open_recommendations_count": 3,
  "portfolio_summary": {
    "total_value": ...,
    "daily_change_pct": ...,
    "layer_weights": {...}
  }
}
```

**LLM output** (short briefing, not exhaustive analysis):
- "Three issues warrant attention today..." opening
- One paragraph per flagged finding, referencing specialist agent conclusion + critic verdict
- One sentence on positions reviewed with no findings
- No raw data tables — the dashboard already shows those

**Prompt construction**: Python assembles the structured JSON above from `agent_findings` and `recommendations` DB rows. The briefing agent makes one LLM call with this compact input.

**Token budget**: expected to be 60–80% smaller than current briefing prompt because specialists have already filtered to what matters.

**Preserve existing endpoint**: `GET /api/ai/daily` still works and returns the briefing; the dashboard AI Insight panel still renders it. Only the generation logic changes.

## Touches

`portfolio_ai.py` (generate_daily_insight function), `agent_db.py` (read findings for today's run), `serve.py` (briefing triggered after orchestrator completes), `generate_dashboard.py` (AI Insight panel unchanged)

## Done when

- [ ] Briefing prompt contains specialist findings, not raw holdings/prices
- [ ] Token count of briefing prompt measurably smaller than current (log both)
- [ ] `GET /api/ai/daily` still returns valid briefing content
- [ ] Briefing references specific ticker findings by name ("Guardian flagged GRMN at 2.3σ...")
- [ ] If no agent findings exist today, briefing gracefully notes "no material findings"
- [ ] Existing AI Insight panel in dashboard renders the new briefing without layout changes
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced

