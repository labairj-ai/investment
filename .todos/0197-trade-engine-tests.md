# Trade Engine Test Suite: Conservation, Idempotency, Edge Cases

- **ID:** 0197
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0193, 0194, 0195, 0196

## Problem

The existing test suite (306 tests) has strong coverage of the analysis and recommendation layer. The execution layer needs an equally rigorous suite focused on the unique failure modes of automated trading: replay attacks, stale intents, crash-restart safety, and the cash/position conservation invariants that must hold under all conditions.

These tests must pass with no broker connection and no live quotes (all mocked).

## Proposed approach

**`tests/test_trade_engine.py`**

### Risk Engine tests (one test per rule)
- TRADING_ENABLED=False → REJECTED with TRADING_ENABLED FAIL
- Expired intent (valid_until in past) → REJECTED with INTENT_NOT_EXPIRED FAIL
- Duplicate recommendation_id (already APPROVED/FILLED intent) → REJECTED with NO_DUPLICATE_INTENT FAIL
- Market order when disallowed → REJECTED with NO_MARKET_ORDER FAIL
- BUY when buy_allowed=False → REJECTED with INSTRUMENT_ALLOWED FAIL
- Insufficient cash (would drop below min_cash_pct) → REJECTED with SUFFICIENT_CASH FAIL
- Position weight would exceed max → REJECTED with MAX_POSITION_WEIGHT FAIL
- New position would exceed max_new_position_pct → REJECTED with MAX_NEW_POSITION_WEIGHT FAIL
- Daily notional exceeded → REJECTED with MAX_DAILY_NOTIONAL FAIL
- Max orders per day exceeded → REJECTED with MAX_ORDERS_PER_DAY FAIL
- SELL with no position → REJECTED with SELL_QUANTITY_COVERED FAIL
- SELL_TO_OPEN with insufficient underlying → REJECTED with NO_NAKED_OPTIONS FAIL
- All checks pass → APPROVED with all PASS checks
- Checks JSON written to risk_decisions table

### Shadow Broker tests
- LIMIT BUY: ask ≤ limit → fills at ask; ask > limit → no fill
- LIMIT SELL: bid ≥ limit → fills at bid; bid < limit → no fill
- MARKET order → REJECTED immediately
- DAY order after 16:00 ET → EXPIRED
- Fill atomically updates: fills table, order fill_qty, position_snapshots, cash
- Duplicate fill_id is idempotent (no double-count)
- Invalid state transition raises InvalidStateTransition

### Cash conservation invariant
```
For any sequence of N fills in any order:
starting_capital
  + sum(sell_fill.qty × sell_fill.price)  -- proceeds
  - sum(buy_fill.qty × buy_fill.price)    -- purchases
  - sum(fill.fee)                          -- fees
== current_cash
```
Test with: 5 buys, 3 partial sells, 1 full exit, 1 failed order (no fill). Check after each step and at end.

### Position conservation invariant
```
For each symbol:
sum(buy fills qty) - sum(sell fills qty) == current position qty
```
Test with multiple partial fills on same symbol.

### Intent Builder tests
- BUY → correct quantity (target weight × NAV / price, floored)
- TRIM → quantity = floor(position × trim_fraction)
- EXIT → quantity = full position
- BUY with quantity < 1 (price too high for min position) → returns None
- EXIT when no agentic position → returns None
- SELL_CC recommendation → returns None (not yet supported)
- Duplicate call for same recommendation_id → returns existing intent (idempotent, no new row)
- Intent written with correct recommendation_id, thesis_version, config_hash

### Execution Engine / idempotency tests
- Crash after order submit (SUBMITTED state) but before fill: re-run finds WORKING order, does not re-submit
- Crash after fill but before executed_actions write: re-run writes executed_actions idempotently (fill_id dedup)
- Shadow fill appears in executed_actions with correct recommendation_id
- Full end-to-end: BUY recommendation → intent → risk approval → shadow fill → executed_actions row → outcome evaluator can read it

## Touches

- `tests/test_trade_engine.py` (new file)

## Done when

- [ ] All 18 risk rules have a dedicated test
- [ ] Shadow broker fill/no-fill mechanics tested for BUY and SELL limit orders
- [ ] Cash conservation invariant tested over a 10-step mixed fill sequence
- [ ] Position conservation tested per-symbol
- [ ] Intent builder: all 4 action types + edge cases (insufficient capital, no position)
- [ ] Execution engine idempotency: crash-after-submit and crash-after-fill scenarios
- [ ] End-to-end test: BUY recommendation → executed_actions row exists
- [ ] All tests pass with no broker connection (yfinance mocked)
