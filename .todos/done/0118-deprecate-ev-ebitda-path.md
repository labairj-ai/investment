# Deprecate Mislabeled EV/EBITDA Storage in Historical Valuation Metrics

- **ID:** 0118
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** low
- **Depends:** 0109

## Problem

`financials_fetcher.py` still writes the EBIT proxy (operating income) into the `ev_ebitda` column of `historical_valuation_metrics`, alongside the correctly-labeled `ev_ebit_proxy` column. This means both columns exist with the same value and the same mislabeled name — a future developer could read `ev_ebitda` and believe it is genuine EBITDA (EV ÷ (EBIT + D&A)), when it is actually EV ÷ operating_income. The Buffett screener's separate `ev_ebitda` column (from `enterpriseToEbitda` in yfinance) IS genuine EBITDA and should remain untouched.

## Proposed approach

- In `financials_fetcher.py`: stop writing to `ev_ebitda` in `historical_valuation_metrics` (pass `None` or drop from the INSERT). Only `ev_ebit_proxy` should carry the ratio.
- In `agent_db.py`: remove `ev_ebitda` from the `_valid` set in `get_valuation_ratio_history()` and update the docstring to note the column is deprecated. Update the `upsert_valuation_metrics` signature/docstring similarly.
- Add a deprecation comment to the `ev_ebitda` column definition in the `historical_valuation_metrics` CREATE TABLE block.
- Do NOT touch `buffett_screener.py` — its `ev_ebitda` is genuinely sourced from `enterpriseToEbitda` and is correct.

## Touches

- `financials_fetcher.py`
- `agent_db.py`

## Done when

- [ ] `financials_fetcher.py` no longer writes operating income into `ev_ebitda` in `historical_valuation_metrics`
- [ ] `get_valuation_ratio_history()` rejects `ev_ebitda` as a valid column (raises or returns empty)
- [ ] `buffett_screener.py` and dashboard EV/EBITDA display unchanged
