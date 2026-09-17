# Enforce Equity-Only LIMIT/DAY Guard in Adapter and Risk Engine

- **ID:** 0311
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** none

## Problem

The Alpaca paper policy explicitly disables all options, but the risk engine only blocks options on `SELL_TO_OPEN` when `covered_calls_allowed` is False — a BUY option intent is not categorically rejected at the risk layer. Additionally, `AlpacaAdapter.submit_order()` performs no pre-flight validation: it silently translates any `TradeIntent` into a broker HTTP request regardless of `instrument_type`, `order_type`, `time_in_force`, or whether `quantity` is a whole number. A non-equity or non-LIMIT intent could reach the network unchecked.

## Proposed approach

**Risk engine (`trade_engine/risk_engine.py`):**
- Add an explicit instrument-type check as the first rule in `evaluate()`: if `intent.instrument_type != InstrumentType.EQUITY`, immediately return `REJECT` with reason `"instrument_type_not_equity"`. This fires before any option-specific policy check, covering all sides and all option types.

**Adapter (`trade_engine/alpaca_adapter.py`):**
- At the top of `submit_order()`, before any network call, validate:
  - `intent.instrument_type == InstrumentType.EQUITY`
  - `intent.order_type == OrderType.LIMIT`
  - `intent.time_in_force == TimeInForce.DAY`
  - `intent.side in {Side.BUY, Side.SELL}`
  - `intent.quantity > 0` and `intent.quantity == int(intent.quantity)` (whole shares)
- Raise `ValueError` (not `BrokerSubmissionIndeterminate`) on any violation — this is a logic fault, not a transient broker error, and should not trigger the crash-recovery path.

**Tests:** add unit tests for each rejected case in both layers.

## Touches

- `trade_engine/risk_engine.py` — new instrument-type guard rule
- `trade_engine/alpaca_adapter.py` — pre-flight validation in `submit_order()`
- `tests/test_alpaca_adapter.py` — cases for each invalid field
- `tests/test_trade_engine.py` or `tests/test_execute_validation.py` — risk engine non-equity reject

## Done when

- [x] Risk engine rejects any intent with `instrument_type != EQUITY` regardless of side or options policy
- [x] `AlpacaAdapter.submit_order()` raises `ValueError` before any HTTP call for non-EQUITY, non-LIMIT, non-DAY, non-BUY/SELL, or fractional-share intents
- [x] Unit tests cover each invalid-field case for both layers
- [x] All existing tests still pass

## Outcome

Adapter pre-flight (submit_order) raises ValueError for non-EQUITY, non-LIMIT, non-DAY, non-BUY/SELL, fractional intents. Risk engine INSTRUMENT_ALLOWED rejects non-EQUITY when covered_calls_allowed=False (correct for multi-strategy — flat rejection would break covered calls). 718 tests pass.
