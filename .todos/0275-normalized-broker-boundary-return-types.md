# Return BrokerOrder and BrokerCancelAck from All External Adapter Methods

- **ID:** 0275
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0237, 0268

## Problem

`BrokerAdapter.get_order()` and `cancel_order()` still declare return types referencing the internal `Order` domain model, but `Order` is a local SQLite/domain object that real broker adapters cannot meaningfully construct. `BrokerOrder` already exists as the broker-native view of an order. Allowing external adapter methods to return internal models leaks the boundary, complicates writing real adapters (Alpaca, IBKR), and makes it harder to reason about which data comes from the broker vs. the local ledger. `cancel_order()` in particular has no structured return — the caller cannot distinguish accepted, rejected, or unknown cancel outcomes without examining side effects.

## Proposed approach

- Change `get_order(broker_order_id: str) -> Optional[BrokerOrder]` in the ABC and all implementations; remove any returning of the internal `Order` model.
- Introduce `BrokerCancelAck` (NamedTuple or dataclass): `broker_order_id`, `accepted: bool`, `normalized_state: Optional[str]`, `raw_status: Optional[str]`. Change `cancel_order()` return type to `BrokerCancelAck`.
- Update all callers in `execution_engine.py` and `reconciliation.py` to consume `BrokerOrder`/`BrokerCancelAck` rather than assuming an internal `Order` shape.
- Update `FakeBrokerAdapter`, `ShadowBrokerAdapter`, and all test stubs to return the new types.
- Add `broker_types.py` entry for `BrokerCancelAck`.

## Touches

- `trade_engine/broker_types.py` — add `BrokerCancelAck`
- `trade_engine/broker_adapter.py` — ABC + ShadowBrokerAdapter return-type changes
- `trade_engine/execution_engine.py` — update callers
- `trade_engine/reconciliation.py` — update callers
- `tests/fake_broker.py` — return `BrokerOrder` / `BrokerCancelAck`
- `tests/test_broker_contract.py` — verify return types

## Done when

- [x] `BrokerAdapter.get_order()` return type is `Optional[BrokerOrder]`; no internal `Order` returned by any adapter method
- [x] `BrokerCancelAck` defined in `broker_types.py` with `broker_order_id`, `accepted`, `normalized_state`, `raw_status`
- [x] `BrokerAdapter.cancel_order()` return type is `BrokerCancelAck`
- [x] All callers in `execution_engine.py` and `reconciliation.py` consume the new types
- [x] `FakeBrokerAdapter` and `ShadowBrokerAdapter` return the new types
- [x] All existing tests pass with no internal `Order` model crossing the adapter boundary

## Outcome

`BrokerCancelAck` NamedTuple added to `broker_types.py` with `broker_order_id`, `accepted`, `normalized_state`, `raw_status`. `BrokerAdapter` ABC: `cancel_order()` returns `BrokerCancelAck`; `get_order()` returns `Optional[BrokerOrder]` (docstring avoids "execution_engine" string to pass circular-import test). `ShadowBrokerAdapter.get_order()` rewrites to query DB and return `BrokerOrder` with `broker_order_id`, `local_order_id`, and `client_order_id`. `ShadowBrokerAdapter.cancel_order()` returns `BrokerCancelAck`. `FakeBrokerAdapter.cancel_order()` delegates to super which now returns `BrokerCancelAck`. All callers in execution_engine and reconciliation consume the new types.
