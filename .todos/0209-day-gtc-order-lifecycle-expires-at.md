# Fix DAY/GTC Order Lifecycle: Explicit expires_at, Pre-Market Stays WORKING

- **ID:** 0209
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`ShadowBroker.attempt_fill()` (shadow_broker.py:85) expires DAY orders whenever `market_calendar.is_market_open()` returns False. A valid DAY order submitted at 8:30 AM ET gets expired immediately — before the 9:30 AM open — because the exchange isn't open yet. The correct behavior is: before today's open → WORKING; during session → eligible; after session close → EXPIRED.

Additionally, GTC orders have no market-session gate at all — `_fill_price()` can match a crossing quote at 3 AM if yfinance returns stale prices. All fills should require an eligible trading session, regardless of TIF. TIF controls expiry only, not session eligibility.

## Proposed approach

1. Add `expires_at TEXT` column to the `Order` dataclass (`models.py`) — optional, populated on submit.
2. Add `expires_at TEXT` to `orders` CREATE TABLE in `agent_db.py:_migrate_trade_engine`.
3. Add `("orders", "expires_at", "TEXT")` to `_new_cols` for migration of existing rows.
4. In `submit_order()` (shadow_broker.py): populate `order.expires_at` from `intent.valid_until` for DAY orders; leave NULL for GTC.
5. Rewrite the TIF check in `attempt_fill()`:
   ```python
   now_str = _now_utc().isoformat()
   # Expire DAY orders that have passed their valid_until
   if order.expires_at and now_str >= order.expires_at:
       self._transition_order(order, OrderState.EXPIRED)
       return None
   # All orders: no fills outside regular session
   if not market_calendar.is_market_open():
       return None  # remain WORKING, no state change
   ```
6. Update `Order.from_db_row()` to read `expires_at`.

## Touches

- `trade_engine/models.py` — `Order` dataclass, `from_db_row()`
- `trade_engine/shadow_broker.py` — `submit_order()`, `attempt_fill()`
- `agent_db.py` — `_new_cols`, `orders` CREATE TABLE in `_migrate_trade_engine()`
- `tests/test_trade_engine.py` — new `TestOrderLifecycle` tests

## Done when

- [ ] DAY order at 8:00 AM ET → remains WORKING (not expired)
- [ ] DAY order at 9:29 AM ET → remains WORKING
- [ ] DAY order at 9:30 AM ET → eligible for fill
- [ ] DAY order at 16:00 ET (expires_at reached) → EXPIRED
- [ ] GTC order at 3:00 AM → no fill (market closed), remains WORKING
- [ ] GTC order during session → eligible for fill
- [ ] Friday after-close DAY order: remains WORKING through weekend, expires Monday
- [ ] All 391 existing tests still pass
