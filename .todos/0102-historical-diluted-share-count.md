# Store Actual Historical Diluted Share Counts

- **ID:** 0102
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** low
- **Depends:** none

## Problem

The historical valuation engine derives shares outstanding from `net_income / EPS` as a fallback. This approximation is distorted by share buybacks, equity issuances, periods with net losses, accounting adjustments, and unusual EPS figures. Because historical EV and market cap depend on share count, distorted share counts flow through to distorted EV/EBITDA and P/E percentiles, which in turn influence TRIM and EXIT thresholds. The effect is worst for companies with significant buyback programs (NFLX, GRMN) or recent losses (JOBY).

## Proposed approach

- Check whether the current financial data provider (`financials_fetcher.py`) already returns diluted weighted-average shares outstanding per period
- If yes: store it in `company_financials` and use it directly in share-count derivation; remove the `net_income / EPS` fallback (or keep only as last resort with a logged warning)
- If no: evaluate whether an alternative provider field (e.g., `commonStockSharesOutstanding`, `sharesOutstandingDiluted`) can be added to the fetch
- Add a `shares_outstanding` column to `company_financials` if not already present
- In the valuation history code, prefer the stored value over the derived value; log a warning when falling back to the derived estimate

## Touches

- `financials_fetcher.py`
- `agent_db.py` (`company_financials` schema)
- `agents/sell_trim_agent.py` (wherever market cap / share count is derived)

## Done when

- [ ] `company_financials` stores actual diluted shares per period for at least the holdings in the portfolio (NFLX, GRMN, UNP, EW, etc.)
- [ ] Valuation history code uses the stored share count when available; falls back with a logged warning when not
- [ ] Unit test: EV/EBITDA for a fixture with known shares outstanding uses the stored value, not the derived estimate
- [ ] No silent fallback: if derived estimate is used, a `[ValuationHistory] WARNING: using derived share count for {ticker}` log line is emitted
- [ ] Regression: sell/trim valuation percentile tests still pass
