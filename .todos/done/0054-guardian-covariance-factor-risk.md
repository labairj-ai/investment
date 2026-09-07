# Expand Portfolio Guardian to Sector/Factor/Covariance Risk

- **ID:** 0054
- **Status:** done
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

## Outcome

- **`config/strategy.json`**: Added 6 new risk thresholds: sector_concentration_pct (35%), portfolio_beta_high/low (1.4/0.6), risk_contribution_multiple (2.0), correlation_cluster_threshold/min_size (0.75/3), covariance_lookback_days (60).
- **`strategy_config.py`**: Exported the 7 new constants.
- **`agents/portfolio_guardian.py`**: Added `_fetch_sector()` (yfinance, module-level cache), `_price_return_matrix()` (multi-day holding_day returns), `_check_sector_concentration()` (sector bucket sum > threshold → finding), `_check_covariance_risk()` (numpy covariance: beta vs portfolio composite, marginal RC, correlation clusters with BFS). All three are called at the end of `run_portfolio_guardian()` after existing per-position checks. Correlation clustering uses BFS on adjacency graph with threshold, finding fires for clusters ≥ 3 members.

## Done when

- [x] Guardian fires a sector-concentration alert when any sector exceeds 35% of portfolio (yfinance sector lookup with module-level cache)
- [x] Portfolio beta is computed and logged each run; alert fires when beta > 1.4 or < 0.6 (beta computed vs portfolio composite return from holding_day)
- [x] Marginal risk contribution computed; findings inserted when RC% > 2× weight%
- [x] Beta and risk contribution use only `holding_day` price history; sector uses yfinance .info (already a project dependency)
- [x] numpy 2.0.2 available in venv and requirements.txt
- [x] **Backend QA:** deployed to optiplex — service active
- [x] **Frontend QA:** no new UI code; findings appear in existing Guardian findings panel
- [x] **No service regression:** service active after deploy
