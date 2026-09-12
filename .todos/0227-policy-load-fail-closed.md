# Fail Closed When Trading Policy Cannot Be Loaded

- **ID:** 0227
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`process_open_orders()` catches any exception from `load_policy()` and sets `policy = None`; the `if policy:` guard then lets the fill loop proceed without risk revalidation. A missing, corrupted, or unreadable policy is an authorization failure, not implicit permission to execute. The invariant must be: no policy → no authority → no fills.

## Proposed approach

- In `process_open_orders()` (`execution_engine.py:368-373`): re-raise (or return early) when `load_policy()` fails; return a result struct with `execution_state="HALTED", halt_reason="POLICY_UNAVAILABLE"`. Do not loop over open orders. Leave WORKING orders untouched — cancellation without policy context is also unauthorized.
- In `process_intent()` (`execution_engine.py:263`): same — if `load_policy()` raises, return a REJECTED/HALTED result with `halt_reason="POLICY_UNAVAILABLE"`.
- In `run_execution_cycle()` (`execution_engine.py:453`): surface `execution_state` and `halt_reason` in the return dict when either sub-call returns POLICY_UNAVAILABLE.
- Tests: mock `load_policy` to raise; assert no fills, no order state changes, telemetry shows HALTED.

## Touches

- `trade_engine/execution_engine.py` — `process_open_orders()`, `process_intent()`, `run_execution_cycle()`
- `tests/test_trade_engine.py`

## Done when

- [ ] `process_open_orders()` returns immediately (no fills) when `load_policy()` raises
- [ ] `process_intent()` returns a HALTED/REJECTED result when `load_policy()` raises
- [ ] `run_execution_cycle()` includes `execution_state="HALTED"` and `halt_reason="POLICY_UNAVAILABLE"` in return dict
- [ ] No WORKING order changes state due to a policy load failure
- [ ] Tests confirm all of the above
