# Fix NYSE Calendar: Dec 24/27 2027 Swap, Add July 3 2028 Early Close

- **ID:** 0212
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`market_calendar.py` contains at least two errors against NYSE's published calendar:

1. `date(2027, 12, 27)` is in `_NYSE_HOLIDAYS` labeled "Christmas (observed, Dec 25 is Sat)". This is wrong: when Christmas falls on Saturday, NYSE observes on the preceding Friday — December 24, 2027. December 27, 2027 (Monday) is a normal trading day. Additionally, `date(2027, 12, 24)` is currently in `_EARLY_CLOSE_DAYS` (early close), but it should be in `_NYSE_HOLIDAYS` (fully closed).

2. `date(2028, 7, 3)` is missing from `_EARLY_CLOSE_DAYS`. NYSE explicitly lists July 3, 2028 (day before Independence Day, which falls on Wednesday) as a 1:00 PM early close day.

These errors cause real behavioral bugs: an order submitted on Dec 27, 2027 would be incorrectly blocked (NYSE is open that day), and a Dec 24, 2027 order would attempt to fill when the exchange is closed.

## Proposed approach

In `market_calendar.py`:
- Remove `date(2027, 12, 27)` from `_NYSE_HOLIDAYS`
- Add `date(2027, 12, 24)` to `_NYSE_HOLIDAYS` (Christmas Day observed — fully closed)
- Remove `date(2027, 12, 24)` from `_EARLY_CLOSE_DAYS`
- Add `date(2028, 7, 3)` to `_EARLY_CLOSE_DAYS` (1:00 PM early close)

Add parameterized tests in `tests/test_trade_engine.py` (or a new `tests/test_market_calendar.py`) that assert known NYSE dates explicitly:
- Dec 24, 2027 → `is_trading_day()=False`
- Dec 27, 2027 → `is_trading_day()=True`
- Jul 3, 2028 → `is_trading_day()=True`, `session_close_time()=time(13,0)`
- Jul 4, 2028 → `is_trading_day()=False`

## Touches

- `trade_engine/market_calendar.py` — `_NYSE_HOLIDAYS`, `_EARLY_CLOSE_DAYS`
- `tests/test_trade_engine.py` (or new `tests/test_market_calendar.py`) — date-specific assertions

## Done when

- [ ] `is_trading_day(date(2027, 12, 24))` returns False (holiday)
- [ ] `is_trading_day(date(2027, 12, 27))` returns True (normal trading day)
- [ ] `session_close_time(date(2028, 7, 3))` returns `time(13, 0)` (early close)
- [ ] `is_trading_day(date(2028, 7, 4))` returns False (Independence Day)
- [ ] All 391 existing tests still pass
