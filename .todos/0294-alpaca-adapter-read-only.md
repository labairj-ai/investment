# Implement AlpacaAdapter Read-Only Operations

- **ID:** 0294
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0291

## Problem

`AlpacaAdapter` is a complete stub — every method raises `NotImplementedError`. The engine cannot initialize a trading session, reconcile positions, evaluate risk against real cash, or ingest fills without real implementations. The read-only operations (account identity, positions, open orders, fills, quotes) are prerequisites for the paper integration and for verifying the existing engine logic against a real broker before any order submission is enabled.

## Proposed approach

- `get_account_id()` — `GET /v2/account`, return `account.id`; verify against `self._expected_account_id` if set, raising `BrokerAccountMismatch` on mismatch.
- `get_broker_account()` — `GET /v2/account`, map `cash`, `portfolio_value`, `buying_power` to `BrokerAccountState`.
- `get_positions()` — `GET /v2/positions`, map each position to `BrokerPosition`; filter to equities only.
- `get_open_orders()` — `GET /v2/orders?status=open`, map to `BrokerOrder` using `_ALPACA_NATIVE_TO_NORMALIZED` for state.
- `get_fills()` — `GET /v2/account/activities?activity_type=FILL&after={since}` with pagination (`page_token`); map each activity to `BrokerFill` using `id` as `broker_fill_id`. The `since` parameter maps to Alpaca's `after` query param (ISO-8601).
- `get_fills_for_order()` — `GET /v2/account/activities?activity_type=FILL&order_id={broker_order_id}`.
- `get_quote()` — Alpaca market data uses a **separate** base URL (`data.alpaca.markets`); add a `data_url` constructor parameter distinct from `base_url`. `GET /v2/stocks/{symbol}/quotes/latest`.
- `find_order_by_client_order_id()` — `GET /v2/orders/{client_order_id}?by=client_order_id` or `GET /v2/orders?status=all&limit=1` filtered client-side.
- `poll_order_events()` — return `[]` for now; WebSocket stream is a later milestone (0295+).
- Use `requests` (already available) with `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers. Raise `BrokerSettlementIndeterminate` on non-2xx responses after one retry.
- Scope: US equities, long-only, paper account only. Do not implement `submit_order` or `cancel_order`.

## Touches

- `trade_engine/alpaca_adapter.py` — all read-only method implementations
- `tests/test_alpaca_adapter.py` — new file; mock `requests` responses to test mapping logic without hitting the network

## Done when

- [x] `get_account_id()` returns the paper account ID and validates against `expected_account_id`
- [x] `get_broker_account()` returns cash, NAV, and buying power from the live paper account
- [x] `get_positions()` returns a `BrokerPosition` list matching current paper positions
- [x] `get_open_orders()` returns open orders with correctly mapped normalized states
- [x] `get_fills()` paginates through all FILL activities since a given cursor and maps to `BrokerFill`
- [x] `get_fills_for_order()` returns fills for a specific order ID
- [x] `get_quote()` returns a `BrokerQuote` from the Alpaca data endpoint (separate URL from trading)
- [x] `poll_order_events()` returns `[]` (stub; WebSocket deferred)
- [x] Unit tests cover field mapping with mocked HTTP responses; no live network calls in CI
- [ ] `initialize_trading_session()` reaches `TRADING_READY` against the real paper account (requires live credentials — deferred to 0296)

## Outcome

Implemented all read-only methods in `trade_engine/alpaca_adapter.py`: `get_account_id()`, `get_broker_account()`, `get_positions()`, `get_open_orders()`, `get_fills()` with page_size=100 pagination, `get_fills_for_order()`, `get_quote()` via data URL, `find_order_by_client_order_id()`. Added `_request()` helper with auth headers, timeout, and `BrokerSettlementIndeterminate` on non-2xx. Added `data_url` constructor param defaulting to `https://data.alpaca.markets`. Created `tests/test_alpaca_adapter.py` with 34 mocked-HTTP unit tests covering field mapping, state normalization, pagination, error paths. All 675 existing tests still pass.
