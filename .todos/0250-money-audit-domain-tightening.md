# Tighten Money and Audit Domain — Decimal, Enums, Timestamps, Source Label

- **ID:** 0250
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0245

## Problem

Four related hygiene issues that will matter once real money flows through:

1. Money and quantities use raw `float` throughout. Floating-point rounding accumulates across fills and can produce incorrect cash/position balances at broker-reconciliation precision.
2. Broker order/fill states are raw strings (`"WORKING"`, `"FILLED"`) rather than enums. Typos or broker-specific state names silently pass through.
3. Timestamps are ISO strings stored and compared as strings; timezone handling is ad hoc and fragile across the codebase.
4. `_write_executed_action()` hardcodes `source="shadow"` and `notes="shadow fill_source=..."`. Once a paper/live adapter exists, real executions would be mislabeled in the audit trail.

## Proposed approach

1. **Decimal for money**: Use `decimal.Decimal` for `price`, `qty`, `cash`, `avg_cost`, `fee` in `Fill`, `BrokerFill`, `BrokerAccountState`, and position math. Convert at DB read/write boundary only. Use `NUMERIC` affinity in SQLite (already works with Decimal).
2. **Broker state enums**: Add `BrokerOrderState(str, Enum)` and `BrokerFillStatus(str, Enum)` in `broker_types.py`. Adapters map broker-native strings to these enums at the boundary.
3. **Timezone-aware timestamps**: Store all datetimes as `datetime` objects internally (UTC); serialize to ISO string only at the DB/JSON boundary. Remove `replace("Z", "+00:00")` hacks throughout.
4. **Audit source label**: Pass `fill_source` through from the adapter (e.g., `"alpaca_paper"`, `"ibkr_live"`, `"shadow"`). `_write_executed_action()` reads `fill.fill_source` rather than hardcoding `"shadow"`.

## Touches

- `trade_engine/broker_types.py`
- `trade_engine/models.py`
- `trade_engine/shadow_broker.py`
- `trade_engine/execution_engine.py`
- `trade_engine/reconciliation.py`
- `tests/test_trade_engine.py`, `tests/test_broker_contract.py`

## Done when

- [ ] `Fill.price`, `Fill.qty`, `Fill.fee` are `Decimal`; cash math uses Decimal throughout
- [ ] `BrokerOrderState` and `BrokerFillStatus` enums exist; adapters map to them at boundary
- [ ] No `replace("Z", "+00:00")` in production code; all datetime parsing uses a single utility
- [ ] `_write_executed_action()` uses `fill.fill_source` — not hardcoded `"shadow"`
- [ ] All tests pass with Decimal arithmetic
