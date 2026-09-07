# Replace EBIT Proxy with True EBITDA in EV/EBITDA History

- **ID:** 0100
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

The historical EV/EBITDA calculation in `sell_trim_agent.py` uses `operating_income` as a proxy for EBITDA. Operating income is EBIT, not EBITDA — it excludes depreciation and amortization. For capital-intensive holdings like UNP (railroads), D&A is a substantial figure and the difference between EBIT and EBITDA can meaningfully distort the historical valuation percentile. The ratio is labeled `ev_ebitda` but is actually closer to `ev_ebit`, misleading both the agent and any manual review.

## Proposed approach

- In the financial data schema, verify whether `company_financials` stores a D&A field (depreciation, amortization, or a combined line). If it does:
  - Compute `ttm_ebitda = _sum("operating_income") + _sum("depreciation_amortization")`
  - Use this in the `ev_ebitda` calculation
- If D&A is not available from the current data provider:
  - Rename the stored ratio key from `ev_ebitda` to `ev_ebit_proxy` everywhere it is written and read, to accurately label what is being measured
  - Add a TODO comment noting that true EBITDA requires D&A sourcing
- Either way: add a test that asserts EV/EBITDA for a capital-intensive company (UNP or similar fixture) differs from EV/EBIT by a non-trivial margin when D&A data is present

## Touches

- `agents/sell_trim_agent.py`
- `financials_fetcher.py` (check if D&A is fetched and stored)
- `agent_db.py` (`company_financials` schema)
- `tests/test_sell_trim_scores.py`

## Done when

- [ ] Either: `ev_ebitda` is computed using `operating_income + depreciation_amortization` (true EBITDA), or the ratio is renamed `ev_ebit_proxy` everywhere it is stored and displayed
- [ ] No code path labels `operating_income` alone as EBITDA
- [ ] Unit test verifies EV/EBITDA value for a fixture with known D&A differs from EV/EBIT by the expected amount
- [ ] Dashboard label matches the actual ratio computed (no misleading column name shown to user)
- [ ] Regression: sell/trim score tests still pass after rename or formula change
