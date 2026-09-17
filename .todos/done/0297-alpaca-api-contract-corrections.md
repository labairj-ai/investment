# Fix Alpaca API Contract Bugs Before Paper Submission

- **ID:** 0297
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0295

## Problem

Four Alpaca API contract bugs in `trade_engine/alpaca_adapter.py` will fail against the real broker despite passing all mocked unit tests. The client-order lookup uses the wrong endpoint (breaks crash-after-submit recovery), the Account Activities call sends the wrong filter parameter (breaks durable fill ingestion), `_request()` calls `resp.json()` on successful 204 responses (throws on a valid cancellation), and only `Timeout`/`OSError` are caught (a connection reset mid-POST becomes an unhandled exception instead of `BrokerSubmissionIndeterminate`).

## Proposed approach

- `find_order_by_client_order_id()`: change to `GET /v2/orders:by_client_order_id?client_order_id=<id>` — the documented Alpaca endpoint for this lookup.
- `get_fills()` / `get_fills_for_order()`: switch from `GET /v2/account/activities?activity_type=FILL` to the specific endpoint `GET /v2/account/activities/FILL` (eliminates the plural-parameter ambiguity and makes the contract explicit).
- `_request()`: add `if resp.status_code == 204: return None` before `resp.json()` to handle successful no-body responses (cancel ACK).
- Exception handling: replace `except (requests.exceptions.Timeout, OSError)` with `except requests.exceptions.RequestException` in `submit_order()` (and anywhere else in `_request()` that can raise during a POST) so connection resets and other transport errors also become `BrokerSubmissionIndeterminate`.

## Touches

- `trade_engine/alpaca_adapter.py` — `find_order_by_client_order_id()`, `get_fills()`, `get_fills_for_order()`, `_request()`, `submit_order()`
- `tests/test_alpaca_adapter.py` — update affected mocked tests to match corrected endpoints; add 204 test for cancel path

## Done when

- [ ] `find_order_by_client_order_id()` calls `GET /v2/orders:by_client_order_id?client_order_id=<id>`
- [ ] `get_fills()` and `get_fills_for_order()` call `GET /v2/account/activities/FILL` (not the generic endpoint with `activity_type` param)
- [ ] `_request()` returns `None` on 204 without calling `resp.json()`
- [ ] `cancel_order()` succeeds when broker returns 204 No Content
- [ ] `submit_order()` raises `BrokerSubmissionIndeterminate` on connection reset (not just Timeout)
- [ ] All existing tests pass with updated mocked endpoints
