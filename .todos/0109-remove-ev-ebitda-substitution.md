# Remove Silent EV/EBITDA-to-EV/EBIT Substitution in Thesis Valuation

- **ID:** 0109
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

`_RATIO_METRIC_MAP` in `sell_trim_agent.py` maps the thesis metric `ev_ebitda` to the DB column `ev_ebit_proxy` silently. Those ratios are not equivalent: EV/EBITDA excludes depreciation and amortization while EV/EBIT does not. If a thesis specifies EV/EBITDA as its primary valuation measure, the agent is scoring against EV/EBIT without telling the user. This makes the sell score misleading for capital-intensive businesses where D&A is large. The internal relabeling done in 0100 is correct, but the thesis-level substitution should either be explicit or eliminated.

## Proposed approach

Option A (preferred, simpler): Remove `ev_ebitda` as a valid `primary_metric` in thesis setup. Replace it with `ev_ebit` as the explicitly named metric. Existing theses stored in the DB with `primary_metric = "ev_ebitda"` should be migrated via a one-time `UPDATE investment_theses` script to `ev_ebit`. The thesis intake draft UI/prompt should no longer offer `ev_ebitda` as a choice. `_RATIO_METRIC_MAP` entry changes from `"ev_ebitda": "ev_ebit_proxy"` to `"ev_ebit": "ev_ebit_proxy"`.

Option B (complete, harder): Fetch D&A from yfinance (`financials_fetcher.py`), store it in `company_financials`, compute true EBITDA = operating_income + D&A, and add an `ev_ebitda` column to `historical_valuation_metrics` that reflects the real ratio.

Proceed with Option A unless D&A data is readily available from yfinance for all holdings.

## Touches

- `agents/sell_trim_agent.py` — `_RATIO_METRIC_MAP`: rename key `ev_ebitda` → `ev_ebit`
- `agents/thesis_intake.py` — remove `ev_ebitda` from the list of offered `primary_metric` options
- `agent_db.py` or a migration script — one-time UPDATE for existing theses
- `generate_dashboard.py` — any UI dropdown or display label referencing "EV/EBITDA"
- `out/dashboard.html` — regenerate
- `tests/test_sell_trim_agent.py` (if exists) or `tests/test_agent_db.py` — update any test that seeds a thesis with `primary_metric = "ev_ebitda"`

## Done when

- [ ] `_RATIO_METRIC_MAP` no longer contains the key `"ev_ebitda"`; it contains `"ev_ebit"` mapping to `"ev_ebit_proxy"`.
- [ ] A thesis with `primary_metric = "ev_ebit"` routes correctly to `ev_ebit_proxy` history and scores without error.
- [ ] A thesis with `primary_metric = "ev_ebitda"` now falls through to the P/E fallback (or raises a clear warning) rather than silently evaluating EV/EBIT.
- [ ] Thesis intake no longer offers `ev_ebitda` as a primary_metric option.
- [ ] Migration script (or `migrate()` in `agent_db.py`) updates any existing DB row with `primary_metric = "ev_ebitda"` to `ev_ebit`; script is idempotent.
- [ ] Dashboard labels show "EV/EBIT" not "EV/EBITDA" wherever the metric appears.
- [ ] `node --check` passes on regenerated `out/dashboard.html`.
- [ ] Full pytest suite passes with no regressions.
- [ ] On optiplex: verify that at least one existing thesis is correctly migrated and that the Sell/Trim agent uses the renamed metric without error in the next agent run.
