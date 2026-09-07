# Briefing Agent: Synthesize Agent Findings + Critic Verdicts

- **ID:** 0062
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** P1
- **Depends:** none

## Problem

The Briefing Agent currently calls `portfolio_ai.generate_daily_insight(force=True)` — which independently re-analyzes the entire portfolio from raw data without any knowledge of what the specialist agents found or what the Critic approved. Two bugs compound this:

1. **Architecture bug**: The briefing ignores `agent_findings` and today's recommendations entirely. The Briefing Agent is supposed to synthesize the pipeline output; instead it runs a parallel analysis that duplicates reasoning the specialists already did.

2. **Confidence bug**: `Recommendation(confidence=1.0)` is passed — but confidence is an int 0–100. `1.0` becomes `1` (1/100 confidence), not 100%.

The correct briefing should tell the user: "Three things deserve your attention today..." based on what the specialists actually found — not a second independent analysis.

## Proposed approach

### 1. Query the day's pipeline output

```python
def _todays_findings(window_hours=24):
    # agent_findings table: group by agent_type, count, list summaries
    ...

def _todays_recommendations(window_hours=24):
    # recommendations table: group by agent_type and action
    ...

def _todays_critic_verdicts(window_hours=24):
    # recommendations with critic_verdict: count APPROVE/CHALLENGE/VETO
    ...
```

### 2. Build a structured briefing prompt

```
PIPELINE SUMMARY — {date}

PORTFOLIO GUARDIAN: {N} findings
  • {summary1}
  • {summary2}

THESIS MONITOR: {N} findings
  • ...

COVERED CALL: {N} opportunities
OPPORTUNITY HUNTER: {N} candidates
SELL/TRIM: {N} recommendations
TAX: {N} findings

CRITIC REVIEW:
  {approved} approved | {challenged} challenged | {vetoed} vetoed

MACRO CONTEXT (for evidence):
  {macro_summary from portfolio_ai — one paragraph, not a full re-analysis}

Based on the above specialist findings, identify the 2–3 most important things
requiring attention today. Be concise; reference specific tickers.
```

### 3. Remove the redundant re-analysis

Replace `portfolio_ai.generate_daily_insight(force=True)` with:
- A lightweight `portfolio_ai.get_macro_summary()` (or read from existing cache) for macro context only
- The structured synthesis prompt above

### 4. Fix the confidence bug

```python
confidence=100,  # was 1.0 — briefing is always "certain" about its own output
```

## Touches

- `agents/briefing_agent.py` — full rewrite of `run_briefing_agent()`
- `agent_db.py` — add helpers to query today's findings/recommendations/verdicts by time window
- `portfolio_ai.py` — optionally add `get_macro_summary()` (non-redundant with full daily insight)

## Done when

- [ ] Briefing prompt includes grouped specialist findings from `agent_findings` table
- [ ] Briefing prompt includes Critic verdict counts (APPROVE / CHALLENGE / VETO)
- [ ] `portfolio_ai.generate_daily_insight()` is NOT called redundantly — at most macro context excerpt
- [ ] `confidence=100` (integer) instead of `1.0`
- [ ] Briefing `rationale` contains actionable synthesis referencing specific tickers
- [ ] **Backend QA:** run full pipeline on optiplex; briefing recommendation rationale reflects today's agent findings
- [ ] **No service regression:** investment service running; briefing email section renders correctly
