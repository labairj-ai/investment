# Expand Portfolio Guardian to Sector/Factor/Covariance Risk

- **ID:** 0054
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

Portfolio Guardian currently checks position concentration, NAV impact, volatility-normalized price moves, and layer drift. The original architecture also envisioned sector concentration, factor exposure, correlation clustering, portfolio beta, and risk contribution. A position could have a modest 5% weight but contribute 20% of portfolio risk due to high correlation with other holdings — and the current Guardian would not detect it. Risk contribution (`RC_i = w_i * (Σw)_i / w^T Σ w`) captures this; nominal weight does not.

## Proposed approach

- Add the following checks to `portfolio_guardian.py`:
  - **Sector concentration**: if any sector exceeds a threshold (e.g. 35%), fire a trigger. Requires a sector mapping (can be stored in `candidate_universe` or a new `ticker_metadata` table, or fetched from yfinance).
  - **Correlation clustering**: compute rolling pairwise correlations from `holding_day` price history; flag clusters of 3+ holdings with correlation > 0.75.
  - **Portfolio beta**: weighted sum of individual betas; alert if > 1.4 or < 0.6 (thresholds in `strategy_config.py`).
  - **Risk contribution**: compute marginal risk contribution using the covariance matrix from price returns; flag any position where `RC_i% > 2 × weight_pct`.
- These are portfolio-scope checks, not per-ticker, so they fire `portfolio_scope` trigger events.
- All calculations are deterministic (matrix math from price history); no LLM needed except for rationale.

## Touches

- `agents/portfolio_guardian.py`
- `agents/triggers.py` (new trigger types if needed: `sector_concentration`, `correlation_cluster`, `risk_contribution`)
- `strategy_config.py` (new thresholds)
- May need `numpy` for covariance math — verify it's in `requirements.txt`

## Done when

- [ ] Guardian fires a sector-concentration alert when any sector exceeds 35% of portfolio
- [ ] Portfolio beta is computed and logged each run; alert fires when beta > 1.4
- [ ] Marginal risk contribution computed; at least one finding in DB for a test portfolio
- [ ] All new calculations use only `holding_day` price history (no external API calls)
- [ ] `numpy` (or equivalent) available in the venv and `requirements.txt`
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change
