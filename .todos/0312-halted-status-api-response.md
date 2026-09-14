# Surface HALTED State Accurately in Execution Cycle API Responses

- **ID:** 0312
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0308

## Problem

`_handle_trade_engine_run()` and `_handle_trade_engine_run_alpaca()` always return HTTP 200 with `"ok": true` when `session.run_cycle()` completes without raising. But `run_execution_cycle()` can legitimately return `execution_state="HALTED"` with a `halt_reason` (e.g. `BROKER_STATE_INTEGRITY`, `SUBMISSION_INDETERMINATE`, `POLICY_UNAVAILABLE`). An external scheduler, monitoring script, or dashboard panel currently cannot distinguish a halted cycle from a healthy one — both look like `200 ok`.

## Proposed approach

- In both `_handle_trade_engine_run()` and `_handle_trade_engine_run_alpaca()`, after `summary = session.run_cycle()`, check `summary.get("execution_state")`.
- If `execution_state == "HALTED"`: return HTTP 409 with `{"ok": false, "execution_state": "HALTED", "halt_reason": summary.get("halt_reason"), ...all other summary fields}`.
- For the `ok=true` path, include `execution_state` and `halt_reason` (as `None`) in the response body regardless — so callers always have the field and don't need to handle its absence.
- Verify `SessionNotReadyError` catch block also sets `halt_reason` in its response body (it currently sets `halt_reason` as a top-level key — confirm it's present and consistent).
- Open question: should 409 be used or 503? 409 Conflict signals "the request was valid but the server state prevents completion"; 503 Service Unavailable implies temporary downtime. Either is defensible; 409 seems more accurate for a halted account.

## Touches

- `serve.py` — `_handle_trade_engine_run()` and `_handle_trade_engine_run_alpaca()` response logic

## Done when

- [ ] A halted cycle (e.g. triggered by a mock `BrokerStateIntegrityError`) returns HTTP 409 with `"ok": false` and a non-null `halt_reason`
- [ ] A healthy cycle returns HTTP 200 with `"ok": true` and `"execution_state"` present in the body
- [ ] `SessionNotReadyError` catch block response includes `halt_reason`
- [ ] Both shadow and Alpaca run handlers are consistent
