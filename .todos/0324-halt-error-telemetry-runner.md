# Complete Halt/Error Telemetry in Trade Runner

- **ID:** 0324
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0315

## Problem

When `session.initialize()` raises `SessionNotReadyError`, `runner.py` returns immediately
from that branch before computing `duration_seconds`, `broker_api_errors`, or broker/local
deltas. The `finally` block still writes a `cycle_runs` row, but `duration_seconds=0` and
`broker_api_errors=0` even when initialization failed because Alpaca was unreachable. This
makes HALTED scorecards indistinguishable from zero-work scorecards, hiding the cause.

Additionally, `broker_api_log` stores `request_id`, `method`, `path`, `status_code`,
`called_at`, and `account_id`, but not `error_type`. The `error_type` field was added to
`_recent_api_calls` for transport failures in 0321, but `_flush_broker_api_log()` discards
it when writing to the DB — losing the ability to distinguish `Timeout` vs `ConnectionError`
vs `SSLError` in burn-in analysis.

## Proposed approach

- **Duration on early return:** record `started_at = time.monotonic()` before any
  `session.initialize()` call; on `SessionNotReadyError` set `duration_seconds =
  time.monotonic() - started_at` before returning so the `finally` block has the real value.
- **API errors on early return:** compute `broker_api_errors` from `adapter._recent_api_calls`
  in the `SessionNotReadyError` except block (same logic as the OK path) and store in `summary`.
- **Broker deltas on early return:** attempt `_broker_local_deltas()` in the finally block
  if `adapter` is live, guarded by try/except; skip gracefully if the session never reached
  a point where broker calls are valid.
- **`error_type` in `broker_api_log`**: add `error_type TEXT` column to `broker_api_log`
  via an ALTER TABLE migration in `agent_db._migrate_trade_engine()`. Update
  `_flush_broker_api_log()` in `runner.py` to include `error_type` in the INSERT.

## Touches

- `trade_engine/runner.py` — SessionNotReadyError path; `_flush_broker_api_log()`
- `agent_db.py` — `_migrate_trade_engine()`: ALTER TABLE `broker_api_log` ADD COLUMN `error_type TEXT`

## Done when

- [x] A cycle that halts during `initialize()` (e.g. Alpaca unreachable) writes a `cycle_runs` row with `duration_seconds > 0` and `broker_api_errors >= 1`
- [x] `broker_api_log` rows written from transport failures include a non-null `error_type` (e.g. `"ConnectionError"`, `"Timeout"`)
- [x] A cycle that halts during `run_cycle()` (post-initialization) also writes correct `duration_seconds`
- [x] All existing tests pass

## Outcome

SessionNotReadyError except block now sets `duration_seconds = time.monotonic() - started_at` and computes `broker_api_errors` from `adapter._recent_api_calls` before returning — the finally block picks up both. `agent_db._migrate_trade_engine()` adds `error_type TEXT` to `broker_api_log`. `_flush_broker_api_log()` now inserts `error_type` via `:error_type` binding (`.get("error_type")` so non-transport calls insert NULL). 722 tests pass.
