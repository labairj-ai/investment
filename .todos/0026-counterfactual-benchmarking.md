# Build Multi-Scenario Counterfactual Benchmarking

- **ID:** 0026
- **Status:** done
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

- [x] SPY daily prices fetched and stored alongside portfolio prices
- [x] Four scenario returns calculated for each matured horizon
- [x] `recommendation_outcomes` stores one row per (recommendation, horizon)
- [x] Horizons only populated after they've actually elapsed (no extrapolation)
- [x] CC outcomes correctly calculate premium-captured vs upside-surrendered
- [x] Aggregated stats (AgentAlpha_vs_Hold, AgentAlpha_vs_SPY, UserOverrideAlpha) computable per agent_type and rationale_class
- [x] Decision Journal shows at least one aggregated stat when ≥ 5 matured outcomes exist
- [x] Browser QA (mandatory — do not skip): With ≥ 5 matured recommendations, run the outcome evaluator and open the dashboard Decision Journal in a browser. Verify: (a) zero JS console errors, (b) at least one aggregated stat (AgentAlpha_vs_Hold, AgentAlpha_vs_SPY, or UserOverrideAlpha) renders, (c) `recommendation_outcomes` rows have correct actual_return values (verify one manually against holding_day prices). Do NOT check this box without completing live browser testing.

## Outcome

**`agent_db.py`:**
- `spy_prices(day TEXT PRIMARY KEY, price REAL)` table added to schema
- Migration: `horizon TEXT` + `hold_return REAL` added to `recommendation_outcomes`
- `insert_outcome()` extended with `horizon` and `hold_return` params
- `upsert_spy_price()` / `get_spy_prices()` helpers for SPY cache
- `get_outcome_alpha_stats()`: returns `agent_alpha_vs_hold` (B−C), `agent_alpha_vs_spy` (B−D), `user_override_alpha` (A−B) overall and per agent_type; requires ≥1 row with all non-null components
- `journal_summary()` includes `matured_horizon_rows` count and `alpha_stats` (populated when ≥5 matured rows)

**`agents/outcome_evaluator.py`** (full rewrite):
- Equity horizons: `1w` `1m` `3m` `6m` `12m` — written only after elapsed
- CC horizons: `at_expiry` `30d_post` `90d_post` — uses expiry from `action_payload_json`
- SPY batch-fetched from yfinance, cached in `spy_prices`; yfinance installed in optiplex venv
- Column mapping: `actual_return`=A (ticker hold), `recommended_path_return`=B (EXIT→0, CC→premium±upside, else hold), `hold_return`=C, `benchmark_return`=D
- `_already_evaluated(rec_id, horizon)` guards per-horizon to prevent double-writes
- `min_age_days` param on `evaluate_matured_recommendations()` for testing override

**`generate_dashboard.py`:**
- `dj-alpha-stats` div added after summary strip
- `_fmtAlpha()` helper with green/red coloring
- `_renderDJSummary()` renders alpha panel when `alpha_stats.total_rows >= 5`

Browser QA result (2026-09-05): 8 QA horizon rows written across ANET/BRK-B/BTC/EW. BRK-B 1w hold_return=0.018289 verified exactly against holding_day prices (entry $498.66 → $507.78). Alpha panel "AGENT PERFORMANCE — 8 MATURED HORIZONS: vs Hold +0.00% vs SPY -0.99% Override Alpha +0.00%" rendered correctly. Zero JS console errors. QA data cleaned up after.

