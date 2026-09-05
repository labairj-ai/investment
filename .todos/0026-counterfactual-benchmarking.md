# Build Multi-Scenario Counterfactual Benchmarking

- **ID:** 0026
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** low
- **Depends:** 0018, 0004

## Problem

The Outcome Evaluator (0018) tracks whether recommendations were followed, but without a benchmark it can't determine if following the recommendation was actually better than alternatives. A sell recommendation that "worked" because the stock fell 5% looks different when SPY fell 8% — the agent's call may have been wrong directionally while still appearing numerically positive. Counterfactual benchmarking is what turns outcome tracking into genuine performance measurement.

## Proposed approach

For every closed recommendation (accepted or rejected), create parallel scenario evaluations:

**Four scenarios:**
- **Scenario A — Actual**: what actually happened (tracked via `user_decisions` + `holding_day`)
- **Scenario B — Agent**: hypothetical return if the recommended action had been executed at the stated price
- **Scenario C — Hold**: return from holding the position unchanged through the evaluation period
- **Scenario D — SPY**: return from deploying the same capital into SPY at the time of the recommendation

**Alpha calculations:**
- `AgentAlpha_vs_Hold = R_Agent - R_Hold`
- `AgentAlpha_vs_SPY = R_Agent - R_SPY`
- `UserOverrideAlpha = R_Actual - R_Agent` (positive = user override outperformed agent)

**Multiple evaluation horizons:**

For equity recommendations (HOLD / TRIM / EXIT / RESEARCH):
- 1 week, 1 month, 3 months, 6 months, 12 months

For covered call recommendations:
- At expiration, 30 days after expiration, 90 days after expiration

All horizons stored separately in `recommendation_outcomes` (add `horizon` column to table from 0004). A recommendation generates N outcome rows, one per horizon.

**Price data source:** `holding_day` table already tracks daily prices. For SPY, fetch from Yahoo Finance on the same days (add SPY to the price tracking pipeline, or use a separate reference price table).

**CC-specific outcome calculation:**
- Agent path: premium captured vs. upside surrendered if assigned
- Hold path: unencumbered position return over same period

**Scheduling:** outcome evaluator runs weekly (as in 0018), but only populates horizons that have matured (a 3-month horizon only calculated after 90 days).

**Aggregated statistics (feeds Decision Journal UI in 0018):**
- Mean AgentAlpha_vs_Hold by agent_type and rationale_class
- Mean AgentAlpha_vs_SPY
- Win rate per agent type (% of recommendations where Scenario B beat Scenario C)
- UserOverrideAlpha distribution — which reason_codes produced positive override alpha?

## Touches

`recommendation_outcomes` table (add `horizon`, `scenario_a_return`, `scenario_b_return`, `scenario_c_return`, `scenario_d_return` columns — migration), `agent_db.py` (outcome writer expanded), `serve.py` (SPY price tracking, weekly evaluator job), `generate_dashboard.py` (Decision Journal stats section from 0018)

## Done when

- [ ] SPY daily prices fetched and stored alongside portfolio prices
- [ ] Four scenario returns calculated for each matured horizon
- [ ] `recommendation_outcomes` stores one row per (recommendation, horizon)
- [ ] Horizons only populated after they've actually elapsed (no extrapolation)
- [ ] CC outcomes correctly calculate premium-captured vs upside-surrendered
- [ ] Aggregated stats (AgentAlpha_vs_Hold, AgentAlpha_vs_SPY, UserOverrideAlpha) computable per agent_type and rationale_class
- [ ] Decision Journal shows at least one aggregated stat when ≥ 5 matured outcomes exist
