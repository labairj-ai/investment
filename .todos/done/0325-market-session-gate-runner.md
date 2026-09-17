# Gate Trade Runner on Live Market Session

- **ID:** 0325
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0315

## Problem

`trade-runner.timer` fires at 09:45, 12:00, and 15:45 ET on weekdays, but the runner
performs no check against the actual market calendar. NYSE holidays and early-close days
(e.g. day before Thanksgiving, Christmas Eve half-session) will trigger a full execution
cycle that reaches the stale-quote circuit breakers before halting — generating avoidable
noise in `cycle_runs` and consuming unnecessary Alpaca API quota. Without this gate,
unattended timer execution will produce unexplained HALTED rows on every market holiday.

## Proposed approach

- Add `get_market_clock()` to `AlpacaAdapter` calling `GET /v1/clock` (Alpaca trading API;
  returns `{"is_open": bool, "next_open": ..., "next_close": ...}`).
- At the top of `runner.run()`, after constructing `adapter` but before acquiring the
  execution lease or opening a DB connection, call `get_market_clock()`. If `is_open` is
  `False`, log `"market closed — skipping cycle (SKIPPED_MARKET_CLOSED)"`, write a minimal
  `cycle_runs` row with `execution_state='SKIPPED'`, and `sys.exit(0)`.
- Open question: should the clock check use the Alpaca trading base URL or data URL?
  `/v1/clock` is on the trading URL (`paper-api.alpaca.markets`).
- Open question: should the gate also consult `GET /v1/calendar` to detect early-close days
  where `is_open` may still be `True` mid-session but the session ends early? Clock alone
  may be sufficient if the timer only fires well inside the session window (09:45, 12:00,
  15:45) and `is_open` will already be `False` on early-close days after 13:00 ET.

## Touches

- `trade_engine/alpaca_adapter.py` — new `get_market_clock()` method
- `trade_engine/runner.py` — market-open check before lease acquisition
- `agent_db.py` — possibly: `cycle_runs` `execution_state` must accept `'SKIPPED'` value
  (currently unconstrained TEXT, so likely no schema change needed)

## Done when

- [x] `AlpacaAdapter.get_market_clock()` returns `{"is_open": bool, "next_open": str, "next_close": str}`
- [x] On a weekend or holiday, runner exits 0 with a `SKIPPED_MARKET_CLOSED` log line and a `cycle_runs` row with `execution_state='SKIPPED'`
- [x] On a normal market day during session hours, runner proceeds to acquire the lease and run the cycle normally
- [x] Unit test: mock `get_market_clock()` returning `is_open=False` → runner exits before acquiring lease; no `ExecutionSession` constructed
- [x] All existing tests pass

## Outcome

`AlpacaAdapter.get_market_clock()` added — calls `GET /v1/clock`, returns `{"is_open": bool, "next_open": str, "next_close": str}`. Market gate added to `runner.run()` after adapter construction: if `is_open=False`, logs `SKIPPED_MARKET_CLOSED`, writes `execution_state='SKIPPED'` row to `cycle_runs`, returns 0. Fail-open: clock check exceptions are caught with a warning and the cycle proceeds. 722 tests pass (4 new runner tests covering: closed→SKIPPED, open→lease, clock-fail→fail-open, HALTED-telemetry).
