# Dedicated Brokerage-Account Binding and Initialization Verification

- **ID:** 0272
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0267, 0271

## Problem

The execution enclave currently opens a broker session without verifying which account it is connected to. A misconfiguration (wrong credentials, wrong environment, wrong account alias) will silently route orders to the wrong account. For a real IBKR or Alpaca adapter this means live-account orders could be sent when only a paper account was intended, or vice versa. There is no early-fail mechanism that catches this before the first order is submitted.

## Proposed approach

- Add `expected_account_id: Optional[str]` to `TradingAccount` (or to `trading_policy.json`) — the broker account ID the enclave is configured to trade.
- Add `get_account_id() -> str` to the `BrokerAdapter` ABC; the adapter fetches the authenticated account's ID from the broker at startup.
- In `run_execution_cycle()` (or a new `initialize_session()` step called once before the first cycle), call `broker.get_account_id()` and compare to `expected_account_id`:
  - **Match or expected_account_id is None**: proceed normally.
  - **Mismatch**: raise `BrokerAccountMismatch(RuntimeError)` and halt the cycle with `halt_reason="ACCOUNT_MISMATCH"`. Log both the expected and actual IDs.
- Add an `account_id` property to `FakeBrokerAdapter` (settable at construction) so tests can exercise both the match and mismatch paths.
- Add a chaos test: construct an adapter whose `get_account_id()` returns a different ID than the policy's `expected_account_id`; assert the cycle halts immediately with `ACCOUNT_MISMATCH` and no orders are submitted.

## Touches

- `trade_engine/broker_adapter.py` — `get_account_id()` ABC method; `ShadowBrokerAdapter` impl
- `trade_engine/execution_engine.py` — pre-cycle account verification; `BrokerAccountMismatch` exception
- `trade_engine/models.py` or `config/trading_policy.json` — `expected_account_id` field
- `tests/fake_broker.py` — `account_id` param; `get_account_id()` impl
- `tests/test_chaos.py` — account mismatch halt test

## Done when

- [x] `BrokerAdapter` ABC requires `get_account_id() -> str`
- [x] `initialize_trading_session()` checks expected_broker_account_id vs broker.get_account_id() at step 0; halts on mismatch
- [x] `expected_broker_account_id = None` (default) → check skipped; confirmed by test
- [x] Chaos tests: match → TRADING_READY, mismatch → HALTED, connectivity failure → HALTED, no config → check skipped
- [x] `BrokerAccountMismatch(RuntimeError)` exception defined (logged but not propagated; returns HALTED)
- [x] 558 tests pass

## Outcome

`get_account_id()` abstract method added to BrokerAdapter; ShadowBrokerAdapter returns `self.account_id`; FakeBrokerAdapter returns `_broker_account_id` (configurable). `TradingPolicy.expected_broker_account_id()` reads from `circuit_breakers.expected_broker_account_id`. `initialize_trading_session()` step 0 loads policy, gets expected ID, calls broker.get_account_id(), compares, returns HALTED on mismatch. Four chaos tests cover all branches.
