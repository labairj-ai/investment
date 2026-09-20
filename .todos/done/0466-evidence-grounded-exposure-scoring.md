# Ground Macro Exposure Scores in Quantitative Company Evidence

- **ID:** 0466
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0464

## Problem

The LLM generates 1–10 macro exposure scores for each ticker using only the ticker symbol and dimension definitions — no quantitative company data is provided. The model never receives foreign revenue percentage, geographic breakdown, debt amount/maturity/duration, fixed/floating split, interest expense sensitivity, historical rate beta, historical dollar beta, commodity/input exposure, pricing-power measures, sourcing geography, tariff exposure, or country revenue breakdown. The scores therefore reflect the model's pretrained general knowledge and judgment, not measured company characteristics. This is especially weak for broad ETFs and funds (VFIAX, VTSAX, SCHD, IGV, FSPTX) where exposure should ideally be derived from underlying portfolio holdings rather than a general impression of the fund's category.

## Proposed approach

- Audit what company evidence is already available in the DB (financials, thesis, estimates) and identify what can be passed to the scoring prompt at low cost
- Minimum viable evidence package per ticker: sector/industry, revenue geography (domestic vs. international %), net debt, interest coverage, historical beta to 10Y yield changes, historical beta to DXY changes — fetch from company_financials or yfinance where available
- For ETFs/funds: attempt to derive macro exposure from top holdings when holdings data is accessible; fall back to fund category description with explicit caveat in stored metadata
- Add an `evidence_quality` field to each stored score row: `full`, `partial`, `none` — so consumers can filter or weight accordingly
- Open question: should evidence gathering be a separate pre-pass that runs before scoring, storing a reusable evidence snapshot per ticker?

## Touches

- Macro scoring prompt builder
- `company_financials` table (possible new columns or queries)
- `holding_macro_scores` schema (add `evidence_quality` column)
- ETF/fund handling path in the scoring module

## Done when

- [ ] Scoring prompt for individual stocks receives at minimum: foreign revenue %, net debt/coverage, sector, and historical rate/dollar beta when available
- [ ] ETF/fund scoring path explicitly notes evidence source (holdings-derived vs. category-impression) in stored metadata
- [ ] Each score row carries an `evidence_quality` field (`full` / `partial` / `none`)
- [ ] Scores generated with `evidence_quality = none` are excluded from Learning Lab feature inputs until 0467 determines a suitable replacement
