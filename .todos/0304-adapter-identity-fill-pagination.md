# Enforce Account Identity in Fills and Paginate get_fills_for_order

- **ID:** 0304
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0298

## Problem

Two gaps remain after 0298. First, `_map_fill()` resolves account identity as `account_id or self._account_id`, which still produces `BrokerFill(account_id=None)` if the adapter was constructed without `expected_account_id` and `get_account_id()` has not been called before `get_fills_for_order()`. A fill with `account_id=None` will fail `apply_broker_fill()`'s identity check, crashing a valid fill application. Second, `get_fills_for_order()` fetches a single page only; the Alpaca `/v2/account/activities/FILL` endpoint is paginated and a multi-leg partial fill with many legs could silently return an incomplete list, causing the engine to under-count fill quantity.

## Proposed approach

- **Identity invariant**: in `_map_fill()`, after resolving `resolved_account_id = account_id or self._account_id`, raise `BrokerSettlementIndeterminate` if `resolved_account_id is None` rather than silently constructing a fill with unknown identity. The error message should instruct the caller to call `get_account_id()` or pass `expected_account_id` at construction.
- **Pagination**: refactor `get_fills_for_order()` to use the same `page_size=100` + `page_token` loop already present in `get_fills()`. Extract the shared pagination logic into a private helper `_paginate_fill_activities(params)` if the duplication is worth removing.
- Add a unit test asserting that `_map_fill()` raises when no account ID is available.
- Add a unit test asserting that `get_fills_for_order()` follows the `page_token` link when the first page is full.

## Touches

- `trade_engine/alpaca_adapter.py` — `_map_fill()`, `get_fills_for_order()`
- `tests/test_alpaca_adapter.py` — new tests for identity raise and per-order pagination

## Done when

- [x] `_map_fill()` raises `BrokerSettlementIndeterminate` when resolved `account_id` is `None`
- [x] `get_fills_for_order()` paginates through all pages using `page_token`, matching the behavior of `get_fills()`
- [x] Unit test: `_map_fill()` with no account ID cache raises rather than returning `BrokerFill(account_id=None)`
- [x] Unit test: `get_fills_for_order()` with a full first page follows `page_token` for the second page
- [x] All existing tests pass

## Outcome

`_map_fill()` raises `BrokerSettlementIndeterminate` when `resolved_account_id is None`.
`get_fills_for_order()` now uses a `page_size=100` + `page_token` pagination loop identical
to `get_fills()`. Added `test_raises_when_no_account_id_available` and
`test_paginates_via_page_token` to `TestGetFillsForOrder`. 702 tests pass.
