# Portfolio Guardian: Cache Sector Classifications in DB

- **ID:** 0148
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

`_fetch_sector()` in `agents/portfolio_guardian.py` calls `yf.Ticker(ticker).info` live on every guardian run (process-level dict cache only — empty on each service restart). If yfinance is rate-limited, down, or returns no sector for a ticker, `_fetch_sector()` returns "Unknown". The concentration check then silently skips that ticker (`if sector == "Unknown": continue`). A portfolio concentrated 45% in Technology with one slow API call becomes invisible to the sector check.

Additionally, this adds latency to every guardian sweep proportional to the number of holdings, even when sectors haven't changed.

## Proposed approach

Add a `holding_sectors` table (or a `sector` column on `holding_day`/`holdings.csv`) to persist sector classifications:

1. Cheapest option: add `sector TEXT` column to `holding_day` table; `financials_fetcher.fetch_all()` writes it when fetching `.info`; guardian reads it from DB with `yfinance` as fallback only when null.
2. Alternatively: dedicated `ticker_metadata` table with `ticker, sector, fetched_at`; guardian checks DB first, falls back to live fetch only when stale (> 7 days).

Option 2 is cleaner. The guardian then:
- Checks `ticker_metadata` for `sector` where `fetched_at > 7 days ago`
- Hits yfinance only for stale/missing entries
- On API failure, uses last-known cached sector instead of silently skipping

This prevents silent sector-check suppression on every service restart or API hiccup.

## Touches

- `agent_db.py` — new `ticker_metadata` table (or extend existing); migration
- `agents/portfolio_guardian.py` — `_fetch_sector()` to check DB first
- `financials_fetcher.py` — optionally write sector alongside other .info data

## Done when

- [ ] `_fetch_sector()` returns last-known sector from DB when yfinance call fails
- [ ] Sector data is refreshed no more than once every 7 days per ticker
- [ ] Existing tests pass
