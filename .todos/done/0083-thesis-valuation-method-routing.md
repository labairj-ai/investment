# Route Valuation Engine by Thesis Primary Metric

- **ID:** 0083
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** low
- **Depends:** none

## Problem

`_score_V()` in `sell_trim_agent.py` uses a single valuation approach for all tickers: historical P/E percentile, with the thesis `valuation_framework.extreme_threshold` as a minor override. This ignores the `primary_metric` and `secondary_metrics` fields that thesis intake captures. For businesses where P/E is not the right metric (e.g., a FCF-compounding business valued on EV/FCF, or a cyclical on EV/EBITDA), the valuation score is systematically wrong and the thesis-defined framework is wasted.

## Proposed approach

- In `_score_V()`, read the thesis's `valuation_framework.primary_metric` (e.g., `"forward_pe"`, `"ev_fcf"`, `"ev_ebitda"`, `"p_b"`, `"dividend_yield"`) from the `investment_theses` table.
- Map `primary_metric` to the corresponding column in `company_financials` (or derive it from available columns).
- Use the same historical percentile ranking logic, but applied to the thesis-defined metric instead of always using `price_to_earnings`.
- Fall back to P/E percentile if no `primary_metric` is defined or the specified metric has insufficient history (< 4 periods).
- Apply `attractive_threshold` and `fair_value_low/high` from `valuation_framework` to set the "cheap" and "expensive" calibration points rather than using generic percentile breakpoints alone.
- Open question: how to handle metrics not stored in `company_financials` (e.g., EV/FCF requires enterprise value + FCF, which may need computation at query time)?

## Touches

- `agents/sell_trim_agent.py` — `_score_V()`, `_valuation_percentile()`
- `agent_db.py` — may need a helper to retrieve `valuation_framework` JSON from `investment_theses`
- `agents/thesis_intake.py` — verify `primary_metric` values are constrained to a known set
- `tests/test_sell_trim_scores.py` — add V score test with non-PE primary metric

## Done when

- [ ] `_score_V()` reads `primary_metric` from the ticker's active thesis and uses it for historical percentile ranking
- [ ] Falls back to P/E when no thesis or insufficient history
- [ ] `attractive_threshold` and `fair_value_low/high` influence the score calibration
- [ ] Test: ticker with `primary_metric = "ev_ebitda"` uses EV/EBITDA history, not P/E
