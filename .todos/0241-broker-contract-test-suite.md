# Broker Contract Test Suite: Every Adapter Must Pass Identical Tests

- **ID:** 0241
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0237, 0238

## Problem

Any concrete `BrokerAdapter` implementation (Shadow, paper Alpaca, IBKR) must exhibit identical behavioral contracts — idempotent order submission, correct state transitions, partial fills, cancellation, fill reconciliation. Currently there is no shared test harness enforcing this. When a paper adapter is written, there's no way to verify it meets the same contract as `ShadowBrokerAdapter`.

`ShadowBrokerAdapter` should be the reference implementation. Any new adapter that passes all contract tests is considered fit for integration.

## Proposed approach

**New file: `tests/test_broker_contract.py`**

Define a `BrokerAdapterContractMixin` that any `TestCase` or pytest class can mix in to run the full suite:

```python
class BrokerAdapterContractMixin:
    """Mix into a test class that provides self.make_adapter() -> BrokerAdapter."""
    
    def test_submit_order_returns_order(self): ...
    def test_submit_order_idempotent(self): ...          # same intent_id → same order
    def test_get_order_after_submit(self): ...
    def test_cancel_order_changes_state(self): ...
    def test_cancel_requested_allows_fill_race(self): ...  # CANCEL_REQUESTED → FILLED is legal
    def test_partial_fill_state(self): ...               # PARTIALLY_FILLED after partial qty
    def test_full_fill_state(self): ...                  # FILLED after full qty
    def test_get_positions_returns_typed_list(self): ... # BrokerPosition typed, not raw tuples
    def test_get_quote_returns_broker_quote(self): ...   # BrokerQuote, not shadow Quote
    def test_get_broker_account_returns_state(self): ... # BrokerAccountState with cash
    def test_get_fills_empty_before_fills(self): ...
    def test_get_fills_returns_fills_after_fill(self): ...
    def test_get_orders_returns_working_order(self): ...
    def test_rejected_order_not_in_working_orders(self): ...
```

**Concrete test class for Shadow:**

```python
class TestShadowBrokerAdapterContract(BrokerAdapterContractMixin):
    def make_adapter(self) -> BrokerAdapter:
        return ShadowBrokerAdapter(_make_conn(), "AGENTIC_SHADOW_01")
```

When a paper adapter is built, it gets its own class:
```python
class TestPaperBrokerAdapterContract(BrokerAdapterContractMixin):
    def make_adapter(self) -> BrokerAdapter:
        return PaperBrokerAdapter(...)
```

The contract tests use the `BrokerAdapter` interface exclusively — no direct `ShadowBroker` calls.

## Touches

- `tests/test_broker_contract.py` — new file; `BrokerAdapterContractMixin` + `TestShadowBrokerAdapterContract`
- `trade_engine/broker_adapter.py` — `ShadowBrokerAdapter` must implement all contract methods (depends on 0237, 0238)

## Done when

- [ ] `BrokerAdapterContractMixin` defines at least 14 contract tests
- [ ] `TestShadowBrokerAdapterContract` passes all 14 tests
- [ ] Tests use only `BrokerAdapter` interface methods (no direct `ShadowBroker` access)
- [ ] `make_adapter()` factory method is the only setup point — pluggable for future adapters
