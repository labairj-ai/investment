# MTM Operational Hardening: Market-Date Close Prices and Schedule Fix

- **ID:** 0364
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0351

## Problem

### 1. Price fetch uses "latest 5 days" not "closing price for this specific date"

`run_mark_to_market()` fetches prices via something like:
```python
hist = yf.download([ticker], period="5d", auto_adjust=False)
close = hist["Close"].iloc[-1]
```

This gets the most recent available close, which on a weekend or holiday will be the previous Friday's close — giving a stale NAV date mismatch. It also means a MTM run on a holiday could silently use a price from days ago without flagging it.

### 2. No incomplete-row flag

If a ticker mark cannot be obtained, the NAV row is written silently using average cost as a fallback. A cost-basis fallback is indistinguishable in the table from a real mark, making bad rows look clean.

### 3. systemd TIMEZONE directive may not control the timer

The `book-mtm.timer` uses:
```
TIMEZONE=America/New_York
OnCalendar=Mon..Fri *-*-* 18:30:00
```

The `TIMEZONE=` directive is a unit-file key, but systemd's calendar expressions can include an IANA timezone directly in the `OnCalendar=` value. The standalone `TIMEZONE=` behavior should be verified — if it is silently ignored, the timer fires in UTC (23:30 UTC = 18:30 ET only during EST; during EDT it fires at 22:30 UTC = 18:30 ET, so it coincidentally works in summer but drifts in winter). The safe fix is to embed the timezone in the expression.

## Proposed approach

### Fetch close for the specific requested date

```python
def _get_closing_price(ticker: str, date_str: str) -> float | None:
    """Fetch the official closing price for date_str. Returns None if unavailable."""
    import yfinance as yf
    from datetime import date, timedelta
    d = date.fromisoformat(date_str)
    # Request a 3-day window ending on the target date
    hist = yf.download(ticker, start=d - timedelta(days=3), end=d + timedelta(days=1),
                       auto_adjust=False, progress=False)
    if hist.empty:
        return None
    # Only use a row whose date matches date_str exactly
    if date_str in hist.index.astype(str).tolist():
        return float(hist.loc[date_str, "Close"].iloc[0])
    return None  # no data for this specific date (holiday/weekend)
```

### Skip non-market days

Before running MTM, check if `date_str` is a market day:
```python
from trade_engine.market_calendar import is_market_open_on_date
if not is_market_open_on_date(date_str):
    return  # nothing to mark; don't write a partial row
```

Add `is_market_open_on_date(date: str) -> bool` to `market_calendar.py` if it doesn't exist.

### `virtual_book_nav` incomplete flag

Add `is_complete BOOLEAN DEFAULT 1` column. When any ticker's close price is unavailable, write the row with `is_complete = 0` and log a warning. Dashboard and `mtm_rows_available()` should only count rows where `is_complete = 1`.

### systemd timer fix

Change `book-mtm.timer` to embed the timezone in the calendar expression:
```ini
[Timer]
OnCalendar=Mon..Fri *-*-* 18:30:00 America/New_York
Persistent=true
```

Remove the standalone `TIMEZONE=` line. Validate on optiplex:
```bash
systemctl list-timers book-mtm.timer
```
and confirm the `NEXT` column shows the correct local time.

Apply the same fix to `outcome-labeler.timer` and any other timers using `TIMEZONE=`.

## Touches

- `agents/learning/book_mtm.py` — `_get_closing_price()` uses exact-date fetch; skip non-market days; write `is_complete` flag
- `agent_db.py` — migration: add `is_complete BOOLEAN DEFAULT 1` to `virtual_book_nav`
- `trade_engine/market_calendar.py` — add `is_market_open_on_date(date_str: str) -> bool`
- `systemd/book-mtm.timer` — embed timezone in `OnCalendar=` expression
- `systemd/outcome-labeler.timer` — same fix
- `tests/test_book_simulator.py` — test that non-market-day MTM run writes no rows; test that missing ticker close sets `is_complete=0`; test that `mtm_rows_available()` excludes incomplete rows

## Done when

- [ ] MTM fetches closing price for the exact requested date, not latest available
- [ ] Non-market days are skipped (no row written)
- [ ] `virtual_book_nav.is_complete` column exists; missing mark → `is_complete=0`
- [ ] `mtm_rows_available()` counts only `is_complete=1` rows
- [ ] `book-mtm.timer` uses `OnCalendar=... America/New_York` (no standalone TIMEZONE=)
- [ ] `systemctl list-timers book-mtm.timer` on optiplex shows correct ET next-fire time
- [ ] `python -m pytest tests/` passes with no regressions
