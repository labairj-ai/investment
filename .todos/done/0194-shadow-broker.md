# ShadowBroker: Simulated Order Lifecycle + Fill Engine

- **ID:** 0194
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0191, 0192, 0193

## Problem

"Assume filled at current price" is not a useful simulator. It masks slippage, spread, and liquidity failures that the real broker will surface. The shadow broker must behave enough like a real broker to catch these problems before real money is connected.

The shadow broker owns the order state machine. Nothing else transitions order state directly.

## Proposed approach

**`trade_engine/shadow_broker.py`**

```python
class ShadowBroker:
    def submit_order(self, intent: TradeIntent, approved_by: str) -> Order: ...
    def attempt_fill(self, order: Order, quote: Quote) -> Fill | None: ...
    def cancel_order(self, order_id: str) -> Order: ...
    def get_order(self, order_id: str) -> Order: ...
    def get_positions(self, account_id: str) -> dict[str, float]: ...
    def get_cash(self, account_id: str) -> float: ...
```

**Order state machine** (only valid transitions):
```
PENDING → SUBMITTED → WORKING → FILLED
                   ↘ PARTIALLY_FILLED → FILLED
                   ↘ CANCELLED
                   ↘ REJECTED
                   ↘ EXPIRED (if DAY order after market close)
                   ↘ ERROR
```
Any transition not in the allowed set raises `InvalidStateTransition`.

**Fill simulation rules:**
- LIMIT BUY: fills when quote.ask <= limit_price, at min(quote.ask, limit_price)
- LIMIT SELL: fills when quote.bid >= limit_price, at max(quote.bid, limit_price)
- SELL_TO_OPEN (CC): fills when quote.bid >= limit_price, at max(quote.bid, limit_price)
- BUY_TO_CLOSE: fills when quote.ask <= limit_price, at min(quote.ask, limit_price)
- MARKET orders: rejected by default (policy.market_orders_allowed=False)
- DAY orders: auto-EXPIRED if not filled by 16:00 ET

Quote source for shadow mode: `yfinance` (same as the rest of the codebase). Option quotes come from the options chain.

**Account state maintenance:**
After each fill, the shadow broker atomically updates:
- `fills` table (immutable append)
- `orders` table (fill_qty, fill_cash, state)
- `position_snapshots` (qty += fill.qty for BUY, -= for SELL)
- `trading_accounts.current_cash` (-= fill.qty × fill.price + fill.fee for BUY; += for SELL)

Cash/position conservation invariant must hold after every fill:
```
starting_capital
  + sum(sell fills cash)
  - sum(buy fills cash)
  - sum(fees)
= current_cash + market_value_of_positions
```
(market value is approximate for conservation check — use fill prices, not live quotes)

**Idempotency:** `submit_order()` writes order row before touching broker. On restart, any SUBMITTED order that has no fill and is not cancelled is re-queried (for paper/live; for shadow: assumed no-fill pending re-evaluation). This prevents double-submission on crash.

## Touches

- `trade_engine/shadow_broker.py`
- `agent_db.py` — write helpers for fills, orders, position_snapshots, account cash updates (atomic transaction)
- `tests/test_trade_engine.py`

## Done when

- [ ] `submit_order()` creates PENDING→SUBMITTED order row before any fill attempt
- [ ] `attempt_fill()` correctly fills LIMIT BUY when ask ≤ limit, no-fill otherwise
- [ ] `attempt_fill()` correctly fills LIMIT SELL when bid ≥ limit, no-fill otherwise
- [ ] MARKET order → REJECTED when policy.market_orders_allowed=False
- [ ] DAY order after 16:00 ET → EXPIRED
- [ ] Each fill atomically updates fills + orders + position_snapshots + cash
- [ ] Cash conservation invariant holds after 10-fill test sequence
- [ ] Position conservation invariant holds (buy then sell returns to same qty)
- [ ] Duplicate fill_id is silently idempotent (not double-counted)
- [ ] Invalid state transition raises `InvalidStateTransition`
- [ ] Crash/restart: re-processing same intent does not double-submit order
