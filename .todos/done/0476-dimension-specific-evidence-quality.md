# Calculate Per-Dimension Evidence Quality and Fix Fund Scoring

- **ID:** 0476
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0466

## Problem

The single `evidence_quality` field ("full"/"partial"/"none") is computed by counting how many fields are present in total, without regard to which fields matter for which dimension. A ticker with `sector + gross_margin + revenue` scores "full" even though `rate_sensitivity` has no debt/duration evidence and `dollar_sensitivity` has no geographic revenue evidence. Also, `interest_coverage` and `revenue` are fetched from `company_financials` but silently excluded from the LLM prompt, so the model never sees evidence that was already retrieved. For ETFs and funds in the portfolio (VFIAX, VTSAX, SCHD, IGV, FSPTX, etc.), there is no mechanism to derive exposure from constituent holdings — the model scores these on its pretrained impression of the ticker name, which is not a measurable feature.

## Proposed approach

- Replace the single `evidence_quality` with four per-dimension fields:
  - `rate_evidence_quality`: "full" if debt/interest_coverage/net_debt present; "partial" if sector only; "none" otherwise
  - `dollar_evidence_quality`: "full" if foreign_rev_pct present; "partial" if sector with known intl exposure; "none" otherwise
  - `inflation_evidence_quality`: "full" if gross_margin present (pricing power proxy); "partial" if sector; "none" otherwise
  - `geo_evidence_quality`: "full" if sector + any revenue geography available; "partial" if sector only; "none" otherwise
- Include `interest_coverage` and `revenue_ttm` in the LLM prompt when available (they are already fetched, just not passed).
- Detect ETF/fund tickers: check `HOLDING_PROFILES` (already exists in codebase) or use a simple heuristic (ticker in a known fund list or yfinance `quoteType == "ETF" / "MUTUALFUND"`). For identified funds, set all four dimension evidence qualities to `"unsupported"` and include a note in the scores JSON: `"fund_note": "ETF/fund — exposure from constituent holdings not implemented; LLM estimate only"`. Do not mark these as "full" or "partial".
- Store the four per-dimension quality fields in the scores JSON blob.

## Touches

- `portfolio_ai.py` — `_fetch_company_evidence()`, `generate_holding_macro_scores()`, scores JSON structure
- `holding_macro_scores` / `holding_macro_scores_history` (via JSON blob; no schema change needed)

## Done when

- [x] Four per-dimension evidence quality fields replace the single `evidence_quality` field
- [x] `interest_coverage` and `revenue_ttm` are included in the LLM prompt when available
- [x] ETF/fund tickers are detected and their scores carry `"fund_note"` and all four dimension qualities set to `"unsupported"`
- [x] A ticker with only `sector + gross_margin` does not report `rate_evidence_quality = "full"`
