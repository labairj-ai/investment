"""NYSE market calendar: trading days, session open/close, holiday awareness (0203)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional


# ── NYSE holidays 2026-2028 ───────────────────────────────────────────────────
_NYSE_HOLIDAYS: frozenset[date] = frozenset([
    # 2026
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed, Jul 4 is Sat)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
    # 2027
    date(2027, 1, 1),   # New Year's Day
    date(2027, 1, 18),  # MLK Day
    date(2027, 2, 15),  # Presidents Day
    date(2027, 3, 26),  # Good Friday
    date(2027, 5, 31),  # Memorial Day
    date(2027, 6, 18),  # Juneteenth (observed, Jun 19 is Sat)
    date(2027, 7, 5),   # Independence Day (observed, Jul 4 is Sun)
    date(2027, 9, 6),   # Labor Day
    date(2027, 11, 25), # Thanksgiving
    date(2027, 12, 27), # Christmas (observed, Dec 25 is Sat)
    # 2028
    date(2028, 1, 17),  # MLK Day
    date(2028, 2, 21),  # Presidents Day
    date(2028, 4, 14),  # Good Friday
    date(2028, 5, 29),  # Memorial Day
    date(2028, 6, 19),  # Juneteenth
    date(2028, 7, 4),   # Independence Day
    date(2028, 9, 4),   # Labor Day
    date(2028, 11, 23), # Thanksgiving
    date(2028, 12, 25), # Christmas
])

# NYSE early-close days (1:00 PM ET); typically day after Thanksgiving and Christmas Eve
_EARLY_CLOSE_DAYS: frozenset[date] = frozenset([
    date(2026, 11, 27), # Day after Thanksgiving 2026
    date(2026, 12, 24), # Christmas Eve 2026
    date(2027, 11, 26), # Day after Thanksgiving 2027
    date(2027, 12, 24), # Christmas Eve 2027
    date(2028, 11, 24), # Day after Thanksgiving 2028
    date(2028, 12, 24), # Christmas Eve 2028 (Sun — exchange will be closed but just in case)
])

_OPEN_ET = time(9, 30)
_CLOSE_ET = time(16, 0)
_EARLY_CLOSE_ET = time(13, 0)


def _et_tz():
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo("America/New_York")
    except Exception:
        from datetime import timezone as tz
        return tz(timedelta(hours=-4))  # approx EDT


def _now_et() -> datetime:
    return datetime.now(_et_tz())


def is_trading_day(d: Optional[date] = None) -> bool:
    """Return True if d is a NYSE trading day (not weekend, not holiday)."""
    if d is None:
        d = _now_et().date()
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d not in _NYSE_HOLIDAYS


def session_close_time(d: Optional[date] = None) -> time:
    """Return the market close time (ET) for day d."""
    if d is None:
        d = _now_et().date()
    return _EARLY_CLOSE_ET if d in _EARLY_CLOSE_DAYS else _CLOSE_ET


def is_market_open(now: Optional[datetime] = None) -> bool:
    """Return True if the NYSE is currently open for regular session trading."""
    if now is None:
        now_et = _now_et()
    else:
        now_et = now.astimezone(_et_tz())
    d = now_et.date()
    if not is_trading_day(d):
        return False
    close_t = session_close_time(d)
    return _OPEN_ET <= now_et.time() < close_t


def next_market_close(now: Optional[datetime] = None) -> datetime:
    """Return the next NYSE session close as a timezone-aware datetime."""
    et_tz = _et_tz()
    if now is None:
        now_et = datetime.now(et_tz)
    else:
        now_et = now.astimezone(et_tz)

    d = now_et.date()
    close_t = session_close_time(d)

    if is_trading_day(d) and now_et.time() < close_t:
        # Still before today's close
        close_dt = datetime.combine(d, close_t)
        try:
            return close_dt.replace(tzinfo=et_tz)
        except Exception:
            return close_dt.replace(tzinfo=et_tz)

    # Find next trading day
    d += timedelta(days=1)
    for _ in range(14):  # safety cap
        if is_trading_day(d):
            close_dt = datetime.combine(d, session_close_time(d))
            try:
                return close_dt.replace(tzinfo=et_tz)
            except Exception:
                return close_dt.replace(tzinfo=et_tz)
        d += timedelta(days=1)

    # Fallback: T+1 4 PM ET (should never hit)
    fallback = datetime.combine(now_et.date() + timedelta(days=1), _CLOSE_ET)
    return fallback.replace(tzinfo=et_tz)


def next_market_open(now: Optional[datetime] = None) -> datetime:
    """Return the next NYSE session open as a timezone-aware datetime."""
    et_tz = _et_tz()
    if now is None:
        now_et = datetime.now(et_tz)
    else:
        now_et = now.astimezone(et_tz)

    d = now_et.date()
    if is_trading_day(d) and now_et.time() < _OPEN_ET:
        open_dt = datetime.combine(d, _OPEN_ET)
        return open_dt.replace(tzinfo=et_tz)

    d += timedelta(days=1)
    for _ in range(14):
        if is_trading_day(d):
            open_dt = datetime.combine(d, _OPEN_ET)
            return open_dt.replace(tzinfo=et_tz)
        d += timedelta(days=1)

    fallback = datetime.combine(now_et.date() + timedelta(days=1), _OPEN_ET)
    return fallback.replace(tzinfo=et_tz)
