# Align Virtual Book Holding Horizon with Learning Target

- **ID:** 0361
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0357

## Problem

`BOOK_HOLD_DAYS = 63` with `timedelta(days=63)` means positions are closed after 63 calendar days (~9 weeks). The learning model is trained on 90-day / 3-month alpha. These objectives are misaligned:

- Model asks: "what predicts 91-day SPY-relative return?"
- Book experiment asks: "what happens if I hold for 63 calendar days?"

Additionally, `_get_holdings()` retains a ticker's `first_buy_date` even after quantity drops to zero. If the same ticker is bought again, the old first_buy_date can persist, making a fresh position appear immediately expired.

## Proposed approach

### Holding duration fix

Two defensible options:
1. **91 calendar days** — simplest, directly matches model target
2. **63 trading sessions** — cleaner for market experiments, ~3 market months

Use **63 trading sessions** (approximately 91 calendar days given holidays/weekends). Reuse `trade_engine/market_calendar.py` to count market sessions between two dates rather than using `timedelta(days=63)`.

```python
BOOK_HOLD_SESSIONS = 63  # trading sessions ≈ 3 market months

def _sessions_held(first_buy_date: str, as_of_date: str) -> int:
    """Count market sessions between two dates (exclusive of first_buy_date)."""
    from trade_engine.market_calendar import trading_sessions_between
    return trading_sessions_between(first_buy_date, as_of_date)
```

`expire_cutoff` logic in `run_mark_to_market()` becomes:
```python
for ticker, h in holdings.items():
    sessions = _sessions_held(h["first_buy_date"], date_str)
    if sessions >= BOOK_HOLD_SESSIONS:
        _emit_synthetic_sell(...)
```

### Re-entry bug fix in `_get_holdings()`

When a SELL drives quantity to zero, remove the ticker from the holdings dict entirely rather than retaining it with `qty=0`. Fresh buys for that ticker start a clean clock.

```python
if qty <= 0:
    del holdings[ticker]  # clean exit; next buy starts fresh
    continue
```

Also: define the experiment as **position-level** (one open position per ticker at a time). If a ticker already has an open position in a book, `record_virtual_fills()` should skip the new BUY for that book rather than adding shares. Lot-level tracking can come later.

### `market_calendar.py` helper

Add `trading_sessions_between(start_date: str, end_date: str) -> int` that counts NYSE trading sessions in the range `(start_date, end_date]` using the existing holiday/early-close calendar.

## Touches

- `agents/learning/book_mtm.py` — rename `BOOK_HOLD_DAYS` → `BOOK_HOLD_SESSIONS`; use `_sessions_held()` for expiry check
- `trade_engine/market_calendar.py` — add `trading_sessions_between()`
- `agents/learning/book_simulator.py` — `_get_holdings()` deletes ticker when qty reaches zero; `record_virtual_fills()` skips BUY if book already holds that ticker
- `tests/test_book_simulator.py` — update `TestHoldingExitPolicy0357` to use session count; add test for re-entry clean-slate; add test that duplicate BUY for same ticker is skipped

## Done when

- [ ] Holding duration counted in trading sessions (63 sessions ≈ 91 calendar days)
- [ ] `trading_sessions_between()` helper exists in `market_calendar.py` and handles weekends/holidays correctly
- [ ] Ticker holdings state fully reset when quantity reaches zero
- [ ] Duplicate BUY for a book that already holds a ticker is silently skipped
- [ ] Test: position opened Jan 1, 63 market sessions counted → synthetic SELL; position re-opened after SELL → fresh clock
- [ ] `python -m pytest tests/` passes with no regressions
