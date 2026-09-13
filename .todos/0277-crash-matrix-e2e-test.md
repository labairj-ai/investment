# End-to-End Crash Matrix Test with Distinct Local and Broker IDs

- **ID:** 0277
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0273, 0274, 0275

## Problem

No single test exercises the full crash/restart/recovery matrix end-to-end with intentionally distinct local and broker IDs. Individual units are tested in isolation (0268 for ID routing, 0270/0274 for PENDING_SUBMIT recovery, 0271 for ACK states), but there is no test that chains: submit → network loss → broker fills before restart → restart → authoritative fill import → exact cash/position/order/intent state verified → zero resubmissions. Without this, a regression in any handoff between these layers could go undetected until it hits a real broker.

## Proposed approach

Build a single parameterized chaos test (or a test class with multiple scenarios) in `tests/test_chaos.py`:

1. Use `FakeBrokerAdapter(distinct_broker_id=True)` so local `order_id ≠ broker_order_id` throughout.
2. Submit an intent; capture the `client_order_id` written to the DB before the network response.
3. Simulate crash: raise `BrokerSubmissionIndeterminate` after submit (response lost).
4. Simulate broker fills the order at a specific authoritative price + fee before restart.
5. Restart: call `initialize_trading_session()` + `run_reconciliation()`.
6. Assert:
   - Order state = FILLED (not WORKING, not PENDING_SUBMIT)
   - Fill row has broker-authoritative price and fee (not synthetic limit_price, not fee=0)
   - Cash balance reflects the authoritative fill price
   - Position reflects the fill quantity
   - Intent state = EXECUTED
   - `submit_order()` was NOT called a second time (zero resubmissions)
7. Additional scenario: broker CANCELLED the order before restart → assert CANCELLED, no position change, intent = CANCELLED, zero resubmissions.

## Touches

- `tests/test_chaos.py` — new `TestCrashMatrixE2E` class
- `tests/fake_broker.py` — may need a way to pre-stage fills before `find_order_by_client_order_id()` returns them

## Done when

- [x] Test exercises submit → response-lost crash → broker fills before restart → restart → reconcile → FILLED with authoritative economics
- [x] Test asserts cash and position match broker fill price+qty (not synthetic values)
- [x] Test asserts `submit_order()` called exactly once (no resubmission on restart)
- [x] Scenario: broker CANCELLED before restart → CANCELLED, no position delta, intent CANCELLED
- [x] Test uses `distinct_broker_id=True` so local ID ≠ broker ID throughout
- [x] All assertions pass without modifying any production code (test only)

## Outcome

`TestCrashMatrixE2E` added to `tests/test_chaos.py`. Uses `FakeBrokerAdapter(distinct_broker_id=True)`. `_do_crash()` helper raises `BrokerSubmissionIndeterminate` to simulate response loss. Test 1: submit → response lost → broker fills at authoritative price+fee before restart → restart → reconcile → FILLED with exact broker price/fee in cash and position, zero resubmissions. Test 2: broker cancelled before restart → CANCELLED, no position delta, intent CANCELLED, zero resubmissions. Both use `distinct_broker_id=True` so local_order_id ≠ broker_order_id throughout.
