# Fix and Prove Market-Session Gate Clock Endpoint

- **ID:** 0326
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0325

## Problem

`AlpacaAdapter.get_market_clock()` calls `GET /v1/clock`, but the correct Alpaca Trading
API paper endpoint is `GET /v2/clock`. `/v1/clock` belongs to Alpaca's Broker API sandbox
(a separate product). Because `runner.run()` fails-open on any clock exception, a 404 from
`/v1/clock` raises `BrokerSettlementIndeterminate`, is caught, and execution proceeds
normally — silently bypassing the market-session gate on every real invocation. The unit
tests do not catch this because they mock `get_market_clock()` rather than exercising the
HTTP path.

Additionally, fail-open is not safe when `ALPACA_PAPER_SUBMISSION_ENABLED=1`. If the clock
check fails in that mode, the runner should halt (not proceed), because an autonomous
trading system should not place orders when it cannot confirm the market is open.

## Proposed approach

- Change `/v1/clock` to `/v2/clock` in `AlpacaAdapter.get_market_clock()`.
- Add a unit test that spies on `_request` (or patches `self._session.request`) and asserts
  `_request("GET", "/v2/clock")` is called — not merely that the method returns a value.
- Add a credential-gated integration test (`@pytest.mark.integration`) in
  `tests/test_alpaca_adapter.py` that calls the real paper endpoint and asserts the response
  dict contains `is_open`, `next_open`, and `next_close` keys.
- In `runner.run()`, differentiate the clock-failure handling by submission mode:
  - `ALPACA_PAPER_SUBMISSION_ENABLED=1`: clock failure → write `cycle_runs` row with
    `execution_state='HALTED'`, `halt_reason='MARKET_CLOCK_UNAVAILABLE'`, return 1.
  - submission disabled: retain current fail-open behaviour (warning log + proceed).
- Add a unit test in `tests/test_runner.py` that asserts the fail-closed path: submission
  enabled + clock exception → exit 1 with HALTED/MARKET_CLOCK_UNAVAILABLE in `cycle_runs`.

## Touches

- `trade_engine/alpaca_adapter.py` — `/v1/clock` → `/v2/clock`
- `trade_engine/runner.py` — fail-closed on clock failure when submission enabled
- `tests/test_alpaca_adapter.py` — `_request` path assertion + integration test
- `tests/test_runner.py` — fail-closed unit test

## Done when

- [x] `get_market_clock()` calls `GET /v2/clock`
- [x] Unit test asserts the `/v2/clock` path is passed to `_request`
- [x] Integration test (`@pytest.mark.integration`) verifies `is_open`, `next_open`, `next_close` present in real paper response
- [x] With `ALPACA_PAPER_SUBMISSION_ENABLED=1`, a clock-check failure halts the runner (exit 1, `MARKET_CLOCK_UNAVAILABLE`) instead of proceeding
- [x] With submission disabled, clock-check failure still fails-open (existing behaviour preserved)
- [x] All existing tests pass

## Outcome

Fixed `/v1/clock` → `/v2/clock` in `get_market_clock()`. Runner clock-failure handling split by submission mode: `ALPACA_PAPER_SUBMISSION_ENABLED=1` → HALTED/MARKET_CLOCK_UNAVAILABLE (fail-closed); disabled → warning + proceed (fail-open). `TestGetMarketClock` added to `test_alpaca_adapter.py` with URL path assertion and is_open mapping tests. `test_get_market_clock_real_endpoint` integration test appended to `test_alpaca_integration.py`. `TestMarketClockFailClosed` added to `test_runner.py` covering both submission-enabled (halt) and submission-disabled (proceed) paths. 727 tests pass, 16 skipped.
