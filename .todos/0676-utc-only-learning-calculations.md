# UTC-Only Learning and Outcome Calculations

- **ID:** 0676
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0669

## Problem

Learning, cohort, and outcome calculations (1-week labels, 1-month labels, 63-session maturity, evidence freshness, news aging, etc.) may operate on timezone-naive or local-time datetime objects. A DST transition can silently add or subtract an hour from a duration calculation, distorting evidence age and cohort boundaries.

## Proposed approach

Review all duration, cohort, and maturity calculations in:
- 1-week, 1-month, 63-session outcome labels
- cohort boundaries and maturity eligibility
- recommendation expiration and holding periods
- implementation shortfall timing
- model observation windows
- evidence freshness (news aging, macro freshness)
- sweep start/completion duration

Ensure all arithmetic operates on timezone-aware UTC values from `parse_timestamp()`. Calendar-day logic (e.g. "same trading day") and trading-session logic (e.g. "63 sessions") must remain explicitly separate from wall-clock elapsed time.

## Touches

- `portfolio_ai.py`, learning agent modules, outcome labeling code
- `time_utils.py` — `parse_timestamp()`, `now_utc()` (from 0669)

## Done when

- [x] Duration calculations operate on timezone-aware UTC values
- [x] DST changes cannot add/subtract an hour from evidence age
- [x] Calendar-day logic and trading-session logic remain explicitly separate
- [x] Session maturity continues to use trading sessions where required
## Outcome

Implemented as part of 0668-0680 batch commit.
