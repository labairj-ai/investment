# Foreign Company and Geopolitical Evidence V2

- **ID:** 0508
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0506

## Problem

ITOCF and MITSF showed geopolitical_risk stddev > 3.0 in the live acceptance run. The root cause is evidence quality: geopolitical_risk is currently inferred from sector + revenue_ttm only — no country exposure, supply-chain geography, regulatory/sanctions exposure, or revenue concentration by region. Asking the LLM for a precise 1–10 geopolitical score without country-level grounding produces noise. Dollar sensitivity for foreign companies is similarly weak without regional revenue breakdown.

## Proposed approach

Extend `company_financials` (or a new `company_geo_profile` table) with:

- `revenue_domestic_pct`: % of revenue from home market
- `revenue_us_pct`: % from United States
- `revenue_em_pct`: % from emerging markets (EM)
- `primary_hq_country`: ISO country code
- `incorporation_country`: ISO country code
- `major_operating_regions`: JSON list of regions (e.g. ["Japan", "US", "China"])
- `supply_chain_concentration`: `"single_country"` / `"diversified"` / `"unknown"`
- `sanctions_exposure`: `"none_known"` / `"indirect"` / `"direct"` / `"unknown"`
- `tariff_sensitivity`: `"low"` / `"medium"` / `"high"` / `"unknown"`

For the initial implementation, populate manually for the 3–5 most unstable tickers (ITOCF, MITSF, and any others flagged by 0506). Do not attempt automatic scraping yet.

Update `_fetch_company_evidence()` to query this table and include the new fields in the evidence block sent to the LLM. Update `geo_evidence_quality`:
- `full`: has HQ country + major regions + sanctions/tariff classification
- `partial`: has HQ country only
- `none`: sector only

## Touches

- `investment.db` — new `company_geo_profile` table or added columns in `company_financials`
- `portfolio_ai.py` — `_fetch_company_evidence()`, `geo_evidence_quality` computation
- Manual data entry for ITOCF, MITSF initially

## Done when

- [ ] `company_geo_profile` table or columns exist with the new fields
- [ ] `_fetch_company_evidence()` queries and includes geo fields in scoring evidence
- [ ] `geo_evidence_quality` upgraded to full/partial/none based on new fields
- [ ] ITOCF and MITSF have at least partial geo profiles entered manually
- [ ] Geopolitical score stddev for ITOCF/MITSF measurably reduced vs prior acceptance run
