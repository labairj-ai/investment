# Session Calendar Single Source of Truth

- **ID:** 0405
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0397

## Problem

Two independent problems remain after 0397:

1. **Duplicate labeling logic**: `outcome_labeler` still manually walks forward through dates calling `trading_sessions_between()` to find the 63-session maturity point instead of using the new `maturity_date()` function. Two implementations of "when does 63-session alpha mature?" will eventually drift.

2. **Off-by-one on weekends/holidays**: `nth_trading_session_before(end_date, n)` decrements the date before checking whether it is a trading session. On a Saturday with n=1 it returns Friday — but the interval (Friday, Saturday] contains zero NYSE sessions. This makes health eligibility one session too permissive when the API is queried on a non-market day.

## Proposed approach

- Replace the manual sessions-v2 forward-walk block in `outcome_labeler` with:
  `h_date = maturity_date(entry_date, "sessions_v2", horizon_label)`
- Fix `nth_trading_session_before()`: only count a day as a session if `is_trading_day(current)` is checked BEFORE decrementing the count. Verify that querying on Saturday/Sunday/holiday gives the same result as the preceding trading day.
- Ensure all callers of eligibility cutoffs (health, readiness, labeling) go through `market_calendar` functions.
- Add a test: call `nth_trading_session_before` with a Saturday `end_date` and confirm the result is identical to calling it with the preceding Friday.

## Touches

- `trade_engine/market_calendar.py` — `nth_trading_session_before()` edge case fix
- `outcome_labeler.py` (or wherever sessions-v2 labeling lives) — replace manual walk with `maturity_date()`
- Tests for off-by-one and weekend invariant

## Done when

- [ ] `outcome_labeler` calls `maturity_date()` for session-exact horizons; no manual session-walk loop remains
- [ ] `nth_trading_session_before(saturday, n)` returns the same date as `nth_trading_session_before(preceding_friday, n)`
- [ ] A test covers the weekend/holiday edge case explicitly
- [ ] No other file implements session-counting forward or backward walks
