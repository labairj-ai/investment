# Safe PENDING_SUBMIT Resolution via Broker client_order_id Lookup

- **ID:** 0270
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0265, 0269

## Problem

After a `BrokerSubmissionIndeterminate` halt (0265), reconciliation finds a PENDING_SUBMIT row with no `broker_order_id`. The current logic resolves this by checking whether any broker order matches — but the matching key used is the ad-hoc expression rather than a dedicated lookup. Worse, if no match is found the cycle can return `TRADING_READY`, silently clearing the indeterminate state even though the broker may actually have the order under the `client_order_id` that was sent pre-crash. This risks a ghost order accumulating a position on the broker side while the local ledger shows nothing.

## Proposed approach

- Add `find_order_by_client_order_id(client_order_id: str) -> Optional[BrokerOrder]` to the `BrokerAdapter` ABC and implement it in `FakeBrokerAdapter` and `ShadowBrokerAdapter`.
- In reconciliation, when a PENDING_SUBMIT row is encountered with no `broker_order_id`, call `find_order_by_client_order_id(row.client_order_id)`:
  - **Found**: treat as a normal open order — attach `broker_order_id`, advance to WORKING, continue.
  - **Not found (definite miss)**: broker confirmed it never received the order; safe to transition to CANCELLED or TRADING_READY only after the adapter explicitly confirms the miss (adapter returns `None`, not a timeout/error).
  - **Lookup raises network error**: remain HALTED — do not guess.
- Add a chaos test: (a) halt with `submit_lost` mode (broker definitely never got it); reconcile; assert order advances to a safe terminal state without ghost on the broker. (b) halt with `submit_timeout` mode (broker has it); reconcile via `find_order_by_client_order_id`; assert order moves to WORKING with correct `broker_order_id`.

## Touches

- `trade_engine/broker_adapter.py` — add `find_order_by_client_order_id()` to ABC and `ShadowBrokerAdapter`
- `tests/fake_broker.py` — implement `find_order_by_client_order_id()` in `FakeBrokerAdapter`
- `trade_engine/reconciliation.py` — PENDING_SUBMIT branch uses new lookup before clearing
- `tests/test_chaos.py` — two-branch indeterminate resolution tests

## Done when

- [x] `BrokerAdapter` ABC exposes `find_order_by_client_order_id()`
- [x] Reconciliation section 3c explicitly resolves all remaining PENDING_SUBMIT rows; never returns TRADING_READY with unresolved PENDING_SUBMIT
- [x] `submit_lost` path: reconcile → CANCELLED (broker confirmed absence)
- [x] `submit_timeout` path: reconcile → WORKING with broker_order_id populated
- [x] Network error during lookup → RECONCILIATION_UNAVAILABLE → HALTED
- [x] 558 tests pass

## Outcome

Reconciliation gained section 3c that iterates remaining PENDING_SUBMIT rows after 3a/3b. For each: calls `broker.find_order_by_client_order_id(cid)`. Found → UPDATE to WORKING. None → UPDATE to CANCELLED. Exception → RECONCILIATION_UNAVAILABLE discrepancy → HALTED. FakeBrokerAdapter.find_order_by_client_order_id() searches `_broker_orders` only (correct: broker ledger, not local DB). ShadowBrokerAdapter impl searches DB for non-PENDING_SUBMIT rows.
