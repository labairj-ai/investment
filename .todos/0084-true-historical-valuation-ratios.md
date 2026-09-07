# True Historical Valuation Ratios

- **ID:** 0084
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

`_score_V()` in `sell_trim_agent.py` uses `METRIC_COLUMN_MAP` to map thesis `primary_metric` values like `"ev_fcf"` → `"free_cash_flow"` and `"ev_ebitda"` → `"operating_income"`, then ranks the raw fundamental values historically. This is not a valuation calculation. Growing FCF will appear at the 100th historical FCF percentile, which the system interprets as expensive — but the stock may have gotten cheaper as FCF grew faster than price. Since valuation is 15% of SellStrength, this can materially push TRIM/EXIT scores in the wrong direction.

## Proposed approach

- Add `historical_valuation_metrics` table to `agent_db.py` (via `migrate()`):
  `(ticker, date, market_cap, enterprise_value, ttm_revenue, ttm_ebitda, ttm_fcf, ttm_eps, pe, ps, ev_revenue, ev_ebitda, ev_fcf, p_fcf)`
- Populate this table in `financials_fetcher.py` (or a new `valuation_fetcher.py`) by computing ratios from existing quarterly financials + price history at each period.
- Rewrite `_score_V()` to look up the actual ratio (e.g., EV/FCF) historically from `historical_valuation_metrics` and percentile-rank the ratio, not the raw fundamental.
- Remove the misleading `METRIC_COLUMN_MAP` entries for non-ratio metrics (`ev_fcf`, `p_fcf`, `ps`, `ev_ebitda`, `ev_revenue`).
- Restrict supported `primary_metric` values to those where the ratio can be reliably computed from stored data. Fall back to P/E when unsupported or < 4 periods of ratio history.
- `attractive_threshold` and `fair_value_high` from `valuation_framework` continue to calibrate the cheap/expensive breakpoints.

## Touches

- `agents/sell_trim_agent.py` — `_score_V()`, `METRIC_COLUMN_MAP`, `_valuation_percentile()`
- `agent_db.py` — new `historical_valuation_metrics` table, migration, upsert helper, query helper
- `financials_fetcher.py` — compute and persist ratio time series when fetching financials
- `tests/test_sell_trim_scores.py` — add V-score test using EV/EBITDA ratio history, not raw EBITDA

## Done when

- [ ] `historical_valuation_metrics` table exists and is populated by the data fetcher
- [ ] `_score_V()` ranks ratio values (e.g., EV/FCF), not raw FCF
- [ ] `METRIC_COLUMN_MAP` entries that mapped to raw fundamentals are removed or corrected
- [ ] Test: ticker with `primary_metric = "ev_ebitda"` uses EV/EBITDA ratio history
- [ ] Fallback to P/E when ratio history has < 4 periods
