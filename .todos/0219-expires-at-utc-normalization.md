# Fix expires_at UTC Normalization in DAY Order Expiry Comparison

- **ID:** 0219
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`submit_order()` stores `expires_at` from `market_calendar.next_market_close().isoformat()`, which returns an ET-offset string (e.g. `2026-09-14T16:00:00-04:00`). `attempt_fill()` builds `now_iso = _now_utc().isoformat()` in UTC (`+00:00`) and compares the two as raw strings. Because `+00:00` sorts lexicographically higher than `-04:00`, a DAY order that should expire at 16:00 ET is marked EXPIRED 4 hours early when wall-clock is, e.g., 13:00 ET / 17:00 UTC.

## Proposed approach

1. In `submit_order()`: normalize at write time — `expires_at = market_calendar.next_market_close().astimezone(timezone.utc).isoformat()`.
2. In `attempt_fill()`: parse before comparing — `expiry = datetime.fromisoformat(order.expires_at).astimezone(timezone.utc)` then `if _now_utc() >= expiry: expire`.
3. Add time-of-day tests patching `shadow_broker._now_utc`: 9:29 ET → WORKING; 16:00 ET → EXPIRED; early-close day 13:00 ET → EXPIRED.

## Touches

- `trade_engine/shadow_broker.py` — `submit_order()`, `attempt_fill()`
- `tests/test_trade_engine.py` — new time-of-day expiry tests

## Done when

- [ ] `submit_order()` stores `expires_at` in UTC ISO format
- [ ] `attempt_fill()` compares aware datetime objects, not raw strings
- [ ] DAY order at 9:29 ET wall-clock → state remains WORKING
- [ ] DAY order at 16:00 ET wall-clock → state transitions to EXPIRED
- [ ] Early-close day: order expires at 13:00 ET, not 16:00 ET
- [ ] All existing tests pass
