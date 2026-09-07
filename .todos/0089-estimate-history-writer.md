# Estimate History Writer

- **ID:** 0089
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0086

## Problem

`agent_db.py` has an `estimate_history` table `(ticker, period, estimate_type, estimate_value, captured_at)` and the `_check_estimate_revision()` function in `dependency_checker.py` queries it. But `financials_fetcher.py` only writes to `company_estimates` (a flat current-value store), never to `estimate_history`. So the dependency checker has no revision trail to compare against, and an ESTIMATE_REVISION dependency can never fire.

## Proposed approach

- In `financials_fetcher.py`, after extracting forward estimates (EPS, revenue, price target) from yfinance, append to `estimate_history` only when:
  - No prior row exists for (ticker, period, estimate_type), OR
  - The new value differs from the most recent row by more than a configurable threshold (e.g., 2%), OR
  - More than 30 days have elapsed since the last row for that (ticker, period, estimate_type).
- Store: ticker, period (e.g., "2027FY", "+1Q"), estimate_type ("EPS", "Revenue", "PriceTarget"), estimate_value, captured_at.
- Add `upsert_estimate_history()` helper to `agent_db.py` that implements the append-only-when-changed logic.
- `_check_estimate_revision()` already queries the two most recent rows per (ticker, period, estimate_type) and computes percentage change — it just needs data.

## Touches

- `financials_fetcher.py` — append to `estimate_history` after fetching estimates for each ticker
- `agent_db.py` — `upsert_estimate_history()` with append-only-when-changed logic; ensure `estimate_history` table is created in `migrate()`
- `tests/` — test: two fetches with a changed estimate produce 2 rows; unchanged estimate produces 1 row

## Done when

- [ ] `financials_fetcher.fetch_all()` appends to `estimate_history` for EPS and Revenue per ticker
- [ ] Second fetch with unchanged estimate does not duplicate the row
- [ ] Second fetch with >2% EPS revision does append a new row
- [ ] `_check_estimate_revision()` can detect a 15%+ revision from the stored trail
