# Replace Heuristic Earnings Date with Authoritative Source

- **ID:** 0075
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0074

## Problem

`_check_earnings_date()` in `dependency_checker.py` infers earnings timing from financial period end + ~45 days. This heuristic can be off by weeks and provides no confidence signal. CC and thesis decisions depend heavily on earnings timing (avoid selling calls before earnings, trigger thesis review after). Using a mechanical estimate instead of a confirmed date creates silent errors in both systems.

## Proposed approach

- Add an `earnings_dates` table (ticker, event_date, confirmed_by, confidence, source, created_at) to `agent_db`.
- Populate it via yfinance `Ticker.calendar` (which provides expected earnings dates) on a scheduled refresh (e.g., weekly or whenever a thesis is evaluated).
- Add a confidence hierarchy: company-confirmed > exchange-confirmed > data-provider estimated > period-end heuristic.
- `_check_earnings_date()` should first look up `earnings_dates` for the ticker; fall back to the current heuristic only when no record exists, and attach the appropriate confidence level.
- Surface confidence in dependency check results so agents can treat low-confidence earnings dates conservatively (e.g., widen the exclusion window from 7 to 14 days when confidence is "estimated").
- Wire `event_calendar` table from 0074 to share earnings dates so both dependency types read from the same source of record.

## Touches

- `agent_db.py` — new `earnings_dates` table
- `agents/dependency_checker.py` — `_check_earnings_date()` rewrite
- A scheduled refresh job or hook in the existing Saturday sweep / daily pipeline
- `tests/test_dependency_checker.py` — add test with seeded authoritative earnings date

## Done when

- [ ] `earnings_dates` table exists in schema
- [ ] `_check_earnings_date()` queries the table before falling back to the period-end heuristic
- [ ] Refresh logic populates the table from yfinance calendar
- [ ] Confidence is stored and used to modulate the exclusion window
- [ ] Test: seeded confirmed date supersedes within window; heuristic fallback used when no record
