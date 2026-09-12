# Policy Failure at Any Cycle Point Must Return HALTED

- **ID:** 0234
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`run_execution_cycle()` (`execution_engine.py:534-538`) catches `PolicyUnavailable` raised by `process_open_orders()` and silently recovers — it sets retry variables to empty and then falls through to the normal `"execution_state": "OK"` return at line 550. The cycle fails closed financially (no fills attempted) but reports healthy to any monitoring system watching the response dict. Once alerting or a dashboard consumer reads this process, an "OK" response when policy was unavailable is a false-positive health signal.

The invariant should be: policy failure at any point in the cycle → `execution_state="HALTED"`, `halt_reason="POLICY_UNAVAILABLE"`.

## Proposed approach

In `run_execution_cycle()`, change the `except PolicyUnavailable` handler around `process_open_orders()` (line 536) from silent recovery to an early return:

```python
try:
    retry_fills, pre_fill_rejections, orders_expired_retry = process_open_orders(account_id, conn)
except PolicyUnavailable as exc:
    _log.error("POLICY_UNAVAILABLE in fill retry for %s: %s", account_id, exc)
    return {**_HALTED_BASE, "halt_reason": "POLICY_UNAVAILABLE"}
```

`_HALTED_BASE` is already defined at line 480. This change makes the behavior symmetric with the top-of-cycle policy failure (line 501) and correctly signals `HALTED` to callers.

Update the existing `TestPolicyLoadFailClosed` test class (`test_run_cycle_halts_on_policy_failure`) which currently patches `load_policy` at the top-of-cycle call. Add a new test that patches only the `process_open_orders`-level policy load to fail and asserts the cycle returns `HALTED`.

## Touches

- `trade_engine/execution_engine.py` — `run_execution_cycle()`, `except PolicyUnavailable` handler (line 536-538)
- `tests/test_trade_engine.py` — new test in `TestPolicyLoadFailClosed`

## Done when

- [ ] `PolicyUnavailable` from `process_open_orders()` causes `run_execution_cycle()` to return `execution_state="HALTED"`, `halt_reason="POLICY_UNAVAILABLE"`
- [ ] No "OK" response is possible after any `PolicyUnavailable` in the cycle
- [ ] New test confirms the fill-retry policy failure path returns HALTED
- [ ] Existing `TestPolicyLoadFailClosed` tests still pass
