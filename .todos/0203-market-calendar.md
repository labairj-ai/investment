# Market Calendar: Block Weekend/Holiday/Out-of-Session Execution

- **ID:** 0203
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0199

## Problem

`_is_after_market_close()` only tests `ET hour >= 16`. Saturday at 11 AM passes as a valid trading session. Weekends, NYSE holidays, and early-close days are not handled. IntentBuilder generates `valid_until` using a naive "next 4 PM ET" calculation that also doesn't understand non-trading days.

Shadow fills can occur on weekends, creating a false historical record.

## Proposed approach

**`trade_engine/market_calendar.py`**:
```python
NYSE_HOLIDAYS: frozenset[date]  # hardcoded for current + next year, updated annually

def is_trading_day(d: date) -> bool: ...
def is_market_open(now: datetime | None = None) -> bool: ...
def current_session_close(now: datetime | None = None) -> datetime: ...
def next_market_close(now: datetime | None = None) -> datetime: ...
def next_market_open(now: datetime | None = None) -> datetime: ...
```

Initial holiday list: hardcode NYSE 2026–2027 (MLK, Presidents Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas).

Include early-close days (e.g. day before Thanksgiving, Christmas Eve) at 1:00 PM ET.

**Wire in:**
- `ShadowBroker.attempt_fill()`: replace `_is_after_market_close()` with `not market_calendar.is_market_open()`
- `IntentBuilder.build_intent()`: replace naive `_next_market_close_utc()` with `market_calendar.next_market_close()`
- `process_open_orders()`: skip entirely if `not is_trading_day(today)`
- Risk rule `NO_MARKET_ORDER`: note is_market_open() for future use

## Touches

- `trade_engine/market_calendar.py` — new module
- `trade_engine/shadow_broker.py` — use `market_calendar.is_market_open()`
- `trade_engine/intent_builder.py` — use `market_calendar.next_market_close()`
- `trade_engine/execution_engine.py` — guard `process_open_orders()` with `is_trading_day()`

## Done when

- [ ] `is_market_open()` returns False on weekends, NYSE holidays, before 9:30 AM ET, after 4:00 PM ET
- [ ] `is_trading_day()` returns False for Saturdays, Sundays, NYSE holidays
- [ ] `next_market_close()` skips weekends/holidays correctly
- [ ] ShadowBroker: Saturday WORKING order → does not fill (attempt_fill skipped or returns None)
- [ ] IntentBuilder: `valid_until` for an intent created Friday at 3 PM = Friday 4 PM (same day, not Monday)
- [ ] Tests: Saturday → no fill; Christmas Day → no fill; Friday 3:30 PM → market open; Friday 4:15 PM → market closed
