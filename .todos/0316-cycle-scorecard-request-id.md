# Add Execution Cycle Scorecard and Persist Alpaca Request IDs

- **ID:** 0316
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0313

## Problem

Two observability gaps that matter once unattended paper burn-in begins:

1. No per-cycle execution metrics are persisted. After a week of automated cycles it should be possible to query how many ran, how many halted, how many orders were submitted vs risk-rejected, fill count, duplicate replays, broker API errors, and local-vs-broker cash/position drift. Currently none of this survives a service restart.

2. Alpaca explicitly recommends retaining `X-Request-ID` from every API call because it cannot be reconstructed later and is required for support tracing. `AlpacaAdapter._request()` currently discards all response headers.

## Proposed approach

**Cycle scorecard:**
- Add a `cycle_runs` table to `investment.db` via `agent_db._migrate_trade_engine()`:
  `account_id, run_at, execution_state, halt_reason, new_intents_processed, risk_rejections, orders_submitted, fills_applied, duplicate_fills_skipped, broker_api_errors, cash_delta_vs_broker, position_delta_vs_broker`
- Write one row at the end of every `trade_engine/runner.py` cycle regardless of outcome (OK or HALTED). `cash_delta_vs_broker` and `position_delta_vs_broker` come from comparing local DB state to a fresh `get_broker_account()` / `get_positions()` call at cycle end.
- Open question: compute broker-vs-local deltas every cycle (extra two API calls) or only on HALTED cycles?

**Alpaca X-Request-ID:**
- In `AlpacaAdapter._request()`, extract `resp.headers.get("x-request-id")` and log at `DEBUG` level for every call.
- For mutation endpoints (`POST /v2/orders`, `DELETE /v2/orders/*`, `GET /v2/account/activities/FILL`), also write to a `broker_api_log` table: `(request_id TEXT, method TEXT, path TEXT, status_code INTEGER, called_at TEXT, account_id TEXT)`. Read-only calls (quotes, positions) can be log-only.

## Touches

- `agent_db.py` — `_migrate_trade_engine()`: `cycle_runs` and `broker_api_log` tables
- `trade_engine/alpaca_adapter.py` — `_request()`: extract and log `X-Request-ID`; write to `broker_api_log` for mutations
- `trade_engine/runner.py` (new in 0313) — write `cycle_runs` row after each cycle
- `serve.py` — optionally expose `/api/alpaca/cycles` read endpoint for dashboard

## Done when

- [ ] `cycle_runs` table exists; one row written per cycle with all metric columns populated
- [ ] After 10 automated cycles, a single SQL query returns per-cycle OK/HALTED breakdown and aggregate fill/rejection counts
- [ ] `X-Request-ID` appears in journald logs at DEBUG level for every Alpaca API call
- [ ] Mutation calls write a `broker_api_log` row; row survives service restart and is queryable by `request_id`
