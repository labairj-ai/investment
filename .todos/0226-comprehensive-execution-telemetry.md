# Add Comprehensive Execution Telemetry to run_execution_cycle

- **ID:** 0226
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0220

## Problem

`run_execution_cycle()` returns a thin dict: `new_intents_processed`, `open_orders_fills`, `working_orders_checked`, `results`. Fills that happen on first submission (inside `process_intent()`) are not counted separately. `risk_rejections`, `orders_expired`, `fills_on_submission`, `fills_on_retry`, and `total_fills` are all absent. `serve.py` exposes the same thin dict to the dashboard.

## Proposed approach

Update `run_execution_cycle()` to return:
```python
{
    "new_intents_processed": int,   # PENDING intents evaluated
    "new_orders_created": int,      # approved intents that got an order
    "fills_on_submission": int,     # fills from process_intent() first pass
    "risk_rejections": int,         # intents or pre-fill checks REJECTED
    "working_orders_checked": int,  # open orders examined in retry pass
    "fills_on_retry": int,          # fills from process_open_orders()
    "total_fills": int,             # fills_on_submission + fills_on_retry
    "orders_expired": int,          # orders → EXPIRED this cycle
    "results": [...],
}
```
Count expired orders by querying state before/after or tracking in `attempt_fill()`. Update `serve.py` to expose all fields. `risk_rejections` should include both PRE_ORDER (from 0220) and PRE_FILL rejections.

## Touches

- `trade_engine/execution_engine.py` — `run_execution_cycle()` return dict
- `serve.py` — expose new telemetry fields in `/api/trade-engine/run` response
- `tests/test_trade_engine.py` — cycle telemetry tests

## Done when

- [ ] `run_execution_cycle()` returns all 9 fields above
- [ ] `fills_on_submission` counts fills from `process_intent()` first pass
- [ ] `fills_on_retry` counts fills from `process_open_orders()`
- [ ] `total_fills = fills_on_submission + fills_on_retry`
- [ ] `risk_rejections` counts both PRE_ORDER and PRE_FILL rejections
- [ ] `orders_expired` is accurate for the cycle
- [ ] `serve.py` exposes all fields in the run endpoint response
- [ ] Test: one intent fills on submission + one fills on retry → fills_on_submission=1, fills_on_retry=1, total_fills=2
- [ ] All existing tests pass
