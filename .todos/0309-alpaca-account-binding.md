# Require Alpaca Paper Account ID Binding at Initialization

- **ID:** 0309
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0308

## Problem

The account-binding safety gate built in 0272/0276 is not active for the production Alpaca deployment. `trading_policy_agentic_alpaca_01.json` has `expected_broker_account_id: null` and `require_account_binding: false`, and `_handle_trade_engine_run_alpaca()` constructs `AlpacaAdapter` without `expected_account_id`. This means wrong or swapped Alpaca credentials would not be caught at session initialization — orders could reach an unintended account before any mismatch is detected.

## Proposed approach

- Fetch the Alpaca paper account ID by running `GET /v2/account` with the paper credentials (e.g. `curl -H "APCA-API-KEY-ID: ..." -H "APCA-API-SECRET-KEY: ..." https://paper-api.alpaca.markets/v2/account | jq .id`).
- Add `ALPACA_PAPER_ACCOUNT_ID=<id>` to optiplex `/etc/systemd/system/investment.service.d/override.conf`. Do not commit the value to the repo.
- In `_handle_trade_engine_run_alpaca()`, read `os.environ.get("ALPACA_PAPER_ACCOUNT_ID")` and pass as `expected_account_id=` to `AlpacaAdapter`.
- Set `"require_account_binding": true` in `config/trading_policy_agentic_alpaca_01.json` so that a missing env var causes HALTED rather than silent opt-out.
- Open question: should the expected account ID also be stored in `circuit_breakers.expected_broker_account_id` in the policy file, or is env-only sufficient? Env-only keeps it out of the repo; policy-file approach allows the engine to enforce it without the handler passing it explicitly.

## Touches

- `config/trading_policy_agentic_alpaca_01.json` — set `require_account_binding: true`
- `serve.py` — `_handle_trade_engine_run_alpaca()`: read `ALPACA_PAPER_ACCOUNT_ID` from env, pass to adapter
- `/etc/systemd/system/investment.service.d/override.conf` on optiplex — new `ALPACA_PAPER_ACCOUNT_ID` env var

## Done when

- [ ] `require_account_binding: true` in Alpaca policy; missing expected ID causes HALTED not silent skip
- [ ] `AlpacaAdapter` constructed with `expected_account_id` from env in the run handler
- [ ] Deploying with wrong `ALPACA_PAPER_ACCOUNT_ID` causes session init to return HALTED and zero orders submitted
- [ ] `ALPACA_PAPER_ACCOUNT_ID` is not committed to the git repo
