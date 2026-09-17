# Harden Alpaca Credential Guards and Submission Gate

- **ID:** 0300
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0297

## Problem

Four hardening gaps remain before paper submission should be enabled. The `data_url` receives Alpaca credentials in every request header but has no hostname allowlist, unlike `base_url`. The integration submission gate accepts any truthy string (including `"0"`), so `ALPACA_INTEGRATION_SUBMIT=0` would still enable live order tests. Integration submission tests don't require `expected_account_id`, bypassing the account-binding safeguard built into the adapter. And unknown Alpaca order status strings silently become `"WORKING"` instead of failing closed, which could mask a new broker state mid-trade.

## Proposed approach

- **data_url allowlist**: apply the same HTTPS + exact-hostname check to `data_url` that `base_url` already receives — require `https://data.alpaca.markets`. Honor `_allow_custom_url=True` as the existing test escape hatch.
- **Submission gate**: change `if not os.environ.get("ALPACA_INTEGRATION_SUBMIT")` to `if os.environ.get("ALPACA_INTEGRATION_SUBMIT") != "1"` in `test_alpaca_integration.py`.
- **Account ID requirement**: read `ALPACA_EXPECTED_ACCOUNT_ID` from the environment in `_make_adapter()` (or the submission fixture) and pass it as `expected_account_id`; skip the test if the variable is absent.
- **Fail-closed status mapping**: replace `_ALPACA_ORDER_STATUS_MAP.get(raw, "WORKING")` with a lookup that raises `BrokerSettlementIndeterminate` (or a dedicated `UnknownBrokerStatus` subclass) when `raw` is not in the map. Known-but-informational statuses that don't need an event (e.g., `pending_cancel`) should map explicitly to `None` and be filtered out, not defaulted to `WORKING`.

## Touches

- `trade_engine/alpaca_adapter.py` — `__init__()` data_url guard, `_map_order()` fail-closed status lookup
- `tests/test_alpaca_adapter.py` — tests for data_url hostname guard and unknown-status behavior
- `tests/test_alpaca_integration.py` — submission gate string comparison, `ALPACA_EXPECTED_ACCOUNT_ID` requirement

## Done when

- [ ] `AlpacaAdapter.__init__()` rejects `data_url` that is not `https://data.alpaca.markets` (unless `_allow_custom_url=True`)
- [ ] `ALPACA_INTEGRATION_SUBMIT=0` does not enable submission tests; only the exact string `"1"` does
- [ ] Integration submission tests skip when `ALPACA_EXPECTED_ACCOUNT_ID` is not set, and pass it to the adapter when present
- [ ] An unknown Alpaca order status string raises `BrokerSettlementIndeterminate` rather than silently becoming `"WORKING"`
- [ ] Unit tests cover: data_url hostname rejection, unknown status fail-closed behavior
- [ ] All existing tests pass
