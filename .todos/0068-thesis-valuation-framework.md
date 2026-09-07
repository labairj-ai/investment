# Thesis: First-Class Valuation Framework

- **ID:** 0068
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** P2
- **Depends:** 0067

## Problem

Valuation is currently handled differently by each agent — Sell/Trim uses absolute thresholds or percentiles, Covered Call uses strike/premium math, and the Opportunity Hunter uses analyst targets. There is no approved valuation philosophy per position stored in the thesis. This means:

- A TRIM decision could be made using a different valuation methodology than the one the thesis was written with
- The user cannot state "value ANET using EV/FCF historically, not P/E" and have that respected across all agents
- Valuation signals are inconsistent; the user has no single source of truth for "is this expensive or cheap?"

## Proposed approach

### 1. Schema addition

Add a `valuation_framework` JSON column to `investment_theses`:

```sql
ALTER TABLE investment_theses ADD COLUMN valuation_framework TEXT;
-- JSON structure:
{
    "primary_metric": "forward_pe",         -- the canonical metric for this company
    "secondary_metrics": ["ev_fcf", "ps"],  -- supporting metrics
    "historical_period_years": 5,
    "fair_value_range": [30, 45],           -- [low, high] for primary metric
    "attractive_threshold": 30,             -- buy aggressively below this
    "extreme_threshold": 55,               -- trim/exit above this
    "growth_adjustment_method": "peg",     -- null | "peg" | "ev_growth"
    "rationale": "ANET is FCF-generative; EV/FCF preferred over P/E for capex-light networking"
}
```

### 2. Thesis generator integration

The `thesis_intake.py` / thesis generator should populate `valuation_framework` as part of thesis creation. Add a prompt section asking the LLM to specify:
- Which multiple best captures this business
- Historical range (from company_financials)
- Attractive / fair / extreme thresholds based on that multiple's history

### 3. Agent integration

- **Sell/Trim**: read `valuation_framework.primary_metric` from the thesis and use it as V score's primary basis
- **Covered Call**: use `extreme_threshold` as a signal cap (don't write calls if near extreme valuation — stock likely to be sold)
- **Opportunity Hunter**: use `attractive_threshold` as a buy signal input

### 4. Thesis health dashboard

Display the valuation framework on the thesis detail card. Highlight current multiple vs. the range.

## Touches

- `agent_db.py` — schema migration adding `valuation_framework` column
- `agents/thesis_intake.py` — generate `valuation_framework` during intake
- `agents/sell_trim_agent.py` — read framework, use `primary_metric` for V score
- `agents/covered_call_agent.py` — use `extreme_threshold` as signal cap
- `serve.py` — expose `valuation_framework` in thesis API response
- Frontend — display on thesis detail card

## Done when

- [ ] `valuation_framework` column in `investment_theses` schema
- [ ] Thesis generator populates `valuation_framework` for new theses
- [ ] Sell/Trim reads `primary_metric` from thesis and uses it for V score primary basis
- [ ] Covered call checks `extreme_threshold` before writing recommendation
- [ ] UI displays current multiple vs. framework range on thesis card
- [ ] **Backend QA:** create or update a thesis on optiplex; verify framework stored and used in next Sell/Trim run
- [ ] **No service regression:** existing theses without `valuation_framework` degrade gracefully (null → absolute threshold fallback)
