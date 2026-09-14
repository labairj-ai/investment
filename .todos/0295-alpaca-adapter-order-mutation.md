# AlpacaAdapter Order Mutation Behind Submission Gate

- **ID:** 0295
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0292, 0293, 0294

## Problem

`AlpacaAdapter.submit_order()`, `cancel_order()`, and `get_order()` all raise `NotImplementedError`, so the engine cannot place or manage real paper orders. `poll_order_events()` is also a stub returning `[]`, meaning order state changes are only detected via the ledger pull from 0289 rather than the lower-latency polling path. Without a submission gate, adding these implementations carries the risk of accidentally sending orders before the integration is verified end-to-end.

## Proposed approach

- Add a `submission_enabled: bool = False` keyword-only constructor parameter to `AlpacaAdapter`. `submit_order()` raises `RuntimeError("submission_enabled=False; set explicitly to enable paper order submission")` unless it is `True`. This prevents any POST to the broker until the flag is deliberately set.
- `submit_order()` — `POST /v2/orders` with body `{symbol, qty, side, type="limit", time_in_force="day", limit_price, client_order_id}`. On success map the response to `BrokerOrderAck`. On `TimeoutError` or non-2xx raise `BrokerSubmissionIndeterminate` (do NOT retry — the existing PENDING_SUBMIT → `find_order_by_client_order_id()` recovery handles restarts safely).
- `cancel_order()` — `DELETE /v2/orders/{order_id}`, map response to `BrokerCancelAck`.
- `get_order()` — `GET /v2/orders/{order_id}`, map to `BrokerOrder` using `_ALPACA_NATIVE_TO_NORMALIZED`.
- `poll_order_events()` — polling loop: `GET /v2/orders?status=all&after={last_poll_ts}&limit=100`, diff against known local states to emit `BrokerOrderEvent` objects. Store `last_poll_ts` as instance state; initialize to adapter construction time. WebSocket stream replaces this later.
- Scope: US equities, whole shares, long-only, LIMIT orders, DAY time-in-force, paper only (enforced by constructor guard from 0291).

## Touches

- `trade_engine/alpaca_adapter.py` — `submit_order()`, `cancel_order()`, `get_order()`, `poll_order_events()`, `submission_enabled` gate
- `tests/test_alpaca_adapter.py` — mocked HTTP tests for submit/cancel/get/poll; assert gate raises without flag

## Done when

- [x] `submit_order()` raises when `submission_enabled=False` (default)
- [x] `submit_order()` with `submission_enabled=True` posts `POST /v2/orders` with `client_order_id` forwarded and returns a valid `BrokerOrderAck`
- [x] `submit_order()` raises `BrokerSubmissionIndeterminate` on timeout without retrying
- [x] `cancel_order()` calls `DELETE /v2/orders/{order_id}` and returns `BrokerCancelAck`
- [x] `get_order()` calls `GET /v2/orders/{order_id}` and returns `BrokerOrder` with normalized state
- [x] `poll_order_events()` returns `BrokerOrderEvent` list based on polling `GET /v2/orders?status=all&after=...`
- [x] Unit tests cover all methods with mocked HTTP; gate behavior tested without live credentials
- [x] All existing tests pass

## Outcome

Implemented `submit_order()`, `cancel_order()`, `get_order()`, and `poll_order_events()` in `trade_engine/alpaca_adapter.py`. `submission_enabled=False` gate raises `RuntimeError` before any network call. `submit_order()` wraps `_request()` failures as `BrokerSubmissionIndeterminate`. `poll_order_events()` polls `GET /v2/orders?status=all&after={last_poll_ts}` and emits `BrokerOrderEvent` only for actionable terminal states (FILLED, PARTIALLY_FILLED, CANCELLED, EXPIRED, REJECTED). Added 7 new mocked tests in `tests/test_alpaca_adapter.py`. Full suite: 675 passed, 1 skipped.
