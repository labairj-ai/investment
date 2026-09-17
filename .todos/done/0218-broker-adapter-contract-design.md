# Design BrokerAdapter Contract (B1 — Backlog, No Implementation Yet)

- **ID:** 0218
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0209, 0210, 0211, 0212, 0213, 0214, 0215, 0216, 0217

## Problem

After B0.1 (todos 0209-0217) is complete, the next milestone is connecting a real paper-broker (IBKR/Alpaca). The current `ShadowBroker` is tightly coupled to `ExecutionEngine` — `execution_engine.py` constructs a `ShadowBroker` directly. If broker-specific logic bleeds into the execution engine (`if broker == "IBKR": ...`), the abstraction has failed. The goal is for `ExecutionEngine` to be broker-agnostic: it should call a `BrokerAdapter` interface identically whether talking to shadow, paper, or live.

This todo captures the design-only phase. **Do not write implementation code until all B0.1 todos are complete.**

## Proposed approach

Design an abstract `BrokerAdapter` base class in `trade_engine/broker_adapter.py`:

```python
from abc import ABC, abstractmethod

class BrokerAdapter(ABC):
    @abstractmethod
    def get_account(self) -> TradingAccount: ...
    
    @abstractmethod
    def get_positions(self, account_id: str) -> list[PositionSnapshot]: ...
    
    @abstractmethod
    def get_open_orders(self, account_id: str) -> list[Order]: ...
    
    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]: ...
    
    @abstractmethod
    def submit_order(self, intent: TradeIntent) -> Order: ...
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> Order: ...
    
    @abstractmethod
    def replace_order(self, order_id: str, changes: dict) -> Order: ...
    
    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]: ...
    
    @abstractmethod
    def get_fills(self, since: Optional[str] = None) -> list[Fill]: ...
```

Hierarchy:
- `BrokerAdapter` (ABC)
  - `ShadowBrokerAdapter` — wraps current `ShadowBroker`, passes through to SQLite
  - `PaperBrokerAdapter` — IBKR or Alpaca paper account (B1 implementation)

`ExecutionEngine` should accept a `BrokerAdapter` instance instead of constructing `ShadowBroker` directly.

Validation phase: run shadow and paper in parallel, compare fills, measure slippage/discrepancy before going live.

## Touches

- `trade_engine/broker_adapter.py` — new abstract base class (design doc / stub only for now)
- `trade_engine/execution_engine.py` — sketch of how it would accept a `BrokerAdapter`

## Done when

- [x] Design document / interface stub in `trade_engine/broker_adapter.py` describing the full contract
- [x] `BrokerAdapter` ABC defined with all methods above
- [x] `ShadowBrokerAdapter` stub (wraps `ShadowBroker`) showing the mapping
- [x] Comment in `execution_engine.py` marking where `BrokerAdapter` would replace `ShadowBroker(conn)` construction
- [x] No actual IBKR/Alpaca code written (that is B1)
- [x] All 391 existing tests still pass (this is additive only)

## Outcome

BrokerAdapter ABC, ShadowBrokerAdapter, and normalized broker_types.py were fully implemented in 0237/0238. broker_adapter.py (214 lines) has the complete contract, ShadowBrokerAdapter wrapping ShadowBroker, and execution_engine.py accepts a BrokerAdapter parameter throughout. No IBKR/Alpaca code written.
