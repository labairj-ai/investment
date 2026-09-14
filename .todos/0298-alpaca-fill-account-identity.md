# Populate account_id on All AlpacaAdapter BrokerFills

- **ID:** 0298
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0297

## Problem

`AlpacaAdapter.get_fills_for_order()` constructs `BrokerFill` objects with `account_id=None` because no account ID is in scope at the call site. But `apply_broker_fill()` validates `bf.account_id == account_id` and raises `BrokerFillInvalid` on mismatch — so the first real FILLED ACK that triggers `get_fills_for_order()` will halt with a fill-validity error even though the fill is economically correct. The bug is invisible in mocked tests because `FakeBrokerAdapter` always populates `account_id`.

## Proposed approach

- Cache the verified paper account ID as `self._account_id: Optional[str]` on the adapter instance.
- Set it in two places: (1) from `expected_account_id` at construction time if provided, (2) from the broker response inside `get_account_id()` after the optional mismatch check passes.
- Thread `self._account_id` into every `_map_fill()` call so all fill-producing methods (`get_fills()`, `get_fills_for_order()`) always emit `BrokerFill(account_id=self._account_id, ...)`.
- Add a unit test: build an `AlpacaAdapter` with a known `expected_account_id`, mock a per-order fill HTTP response, call `get_fills_for_order()`, and assert the returned `BrokerFill.account_id` equals the expected ID.

## Touches

- `trade_engine/alpaca_adapter.py` — constructor, `get_account_id()`, `_map_fill()`
- `tests/test_alpaca_adapter.py` — new test asserting `account_id` is populated on per-order fills

## Done when

- [ ] `AlpacaAdapter` stores a `_account_id` cache populated from `expected_account_id` at construction or from `get_account_id()` response
- [ ] Every `BrokerFill` returned by `get_fills()` and `get_fills_for_order()` has `account_id` set to the cached value (never `None`)
- [ ] Unit test: `get_fills_for_order()` with mocked HTTP → `BrokerFill.account_id == expected_account_id`
- [ ] All existing tests pass
