# Earnings and Event Calendar Writer

- **ID:** 0088
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0086

## Problem

`agent_db.py` has `refresh_earnings_dates(ticker)` (fetches from yfinance) and `upsert_event_calendar()`, and the `earnings_dates` and `event_calendar` tables exist. But these are never called as part of the normal data collection flow triggered by `financials_fetcher.fetch_all()`. So `_check_earnings_date()` and `_check_event_calendar()` in `dependency_checker.py` have no data to work with; CC recommendations with an EARNINGS_DATE dependency can never be superseded by an earnings date change.

## Proposed approach

- In `financials_fetcher.fetch_all()` (or a companion function called alongside it in `serve.py`), call `agent_db.refresh_earnings_dates(ticker)` for each ticker after fetching financials.
- Call `agent_db.upsert_event_calendar()` for:
  - Earnings date (source = "yfinance", confidence = "high")
  - Ex-dividend date from yfinance `info.get("exDividendDate")`
  - Investor day / material regulatory events if parseable from news/calendar APIs (source = "manual" or "news" with confidence = "low")
- Do not duplicate: check if a row for the same (ticker, event_type, event_date) already exists before inserting.
- Persist: ticker, event_type, event_date, source, confidence, created_at.
- Events with passed dates should be retained (historical record), not deleted.

## Touches

- `financials_fetcher.py` — add earnings + ex-div upsert calls in `fetch_all()`
- `agent_db.py` — `upsert_event_calendar()` deduplification; `refresh_earnings_dates()` may need a force-refresh flag
- `serve.py` — ensure the refresh endpoint also triggers event writes
- `tests/` — test that fetch populates `earnings_dates` and `event_calendar` tables

## Done when

- [ ] `financials_fetcher.fetch_all()` populates `earnings_dates` for every fetched ticker
- [ ] `event_calendar` gets an EARNINGS row per ticker with a future date when available
- [ ] Ex-dividend date from yfinance info is persisted when present
- [ ] `_check_earnings_date()` returns a supersession signal when earnings date has moved inside an open CC expiration window
