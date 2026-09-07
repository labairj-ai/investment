# Use Period-End Shares Outstanding for Market-Cap Calculation

- **ID:** 0111
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** low
- **Depends:** none

## Problem

`company_financials.shares_outstanding` (added in 0102) stores diluted weighted-average shares from the income statement (`Diluted Average Shares`). Market capitalization is computed as `price × shares`, where `price` is the period-end stock price. Using weighted-average shares with a period-end price conflates two different points in time and produces an inaccurate historical market cap for companies with meaningful buyback or issuance activity. The resulting EV figures (and therefore EV-based valuation ratios) carry a silent error proportional to the share count change during the quarter.

## Proposed approach

- In `financials_fetcher.py`, attempt to fetch period-end shares outstanding from the yfinance balance sheet (`ticker.quarterly_balance_sheet`); look for rows like `Ordinary Shares Number`, `Common Stock`, or `Share Issued`.
- Store this in a new column `shares_period_end REAL` on `company_financials`; add a migration in `migrate()`.
- In `compute_valuation_metrics()`: use `shares_period_end` for market-cap and EV calculations when available; fall back to `shares_outstanding` (diluted average) with a warning; retain `shares_outstanding` for EPS-related checks where diluted average is the correct input.
- Log a per-ticker warning when `shares_period_end` is unavailable so it is visible in the fetcher output.
- Update `financials_fetcher.py` to populate the new column in both `q_rows` and `a_rows`.

## Touches

- `financials_fetcher.py` — fetch `shares_period_end`; use it in `compute_valuation_metrics()`
- `agent_db.py` — `migrate()` to add `shares_period_end REAL` column to `company_financials`
- `tests/test_agent_db.py` — verify migration is idempotent; add test that `compute_valuation_metrics()` prefers `shares_period_end` over `shares_outstanding` when both are present
- README — update `company_financials` schema description

## Done when

- [ ] `company_financials` has a `shares_period_end REAL` column; migration is idempotent (runs without error if column already exists).
- [ ] `financials_fetcher._fetch_one()` attempts to read `Ordinary Shares Number` (or equivalent) from the quarterly balance sheet and populates `shares_period_end` when available.
- [ ] `compute_valuation_metrics()` uses `shares_period_end` for market-cap when present; falls back to `shares_outstanding` with a logged warning when not.
- [ ] Unit test: seed a `company_financials` row with both columns populated; confirm market-cap uses `shares_period_end`, not `shares_outstanding`.
- [ ] Unit test: seed a row with only `shares_outstanding`; confirm fallback path fires and produces a non-None market-cap.
- [ ] For at least one real holding (e.g. AAPL or MSFT), the fetched `shares_period_end` value differs from `shares_outstanding` by a non-trivial amount, demonstrating the improvement.
- [ ] Full pytest suite passes.
- [ ] README `company_financials` schema entry updated to reflect both columns.
