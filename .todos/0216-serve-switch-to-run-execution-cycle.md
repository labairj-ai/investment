# Switch serve.py from run_pending_intents to run_execution_cycle

- **ID:** 0216
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`serve.py:5628` imports and calls `run_pending_intents("AGENTIC_SHADOW_01", conn)`. That function is the deprecated compatibility wrapper that calls `run_execution_cycle()` internally but unconditionally returns `[]`. So the API response always reports `{"ok": true, "processed": 0, "results": []}` — even when orders were successfully filled. The B0 task spec explicitly called for `serve.py` to switch to `run_execution_cycle()`.

## Proposed approach

Replace `_handle_trade_engine_run()` in `serve.py`:

```python
def _handle_trade_engine_run(self):
    """POST /api/trade-engine/run — full execution cycle for AGENTIC_SHADOW_01."""
    try:
        from trade_engine.execution_engine import run_execution_cycle
        conn = self._shadow_conn()
        summary = run_execution_cycle("AGENTIC_SHADOW_01", conn)
        conn.close()
        self._json({
            "ok": True,
            "new_intents_processed": summary["new_intents_processed"],
            "working_orders_checked": summary.get("working_orders_checked", 0),
            "fills": summary.get("open_orders_fills", 0),
            "results": summary.get("results", []),
        })
    except Exception as e:
        self._send_json({"ok": False, "error": str(e)}, 500)
```

Also update `run_execution_cycle()` return dict to include `working_orders_checked` (count of open orders examined during `process_open_orders()`), and optionally `expired` and `rejected` counts from order state transitions. This makes the API response useful telemetry.

## Touches

- `serve.py` — `_handle_trade_engine_run()`
- `trade_engine/execution_engine.py` — `run_execution_cycle()` return dict (add `working_orders_checked`)

## Done when

- [ ] `POST /api/trade-engine/run` returns `new_intents_processed` and `fills` with actual counts
- [ ] Response no longer shows `processed: 0` when fills occurred
- [ ] `run_execution_cycle()` return dict includes `working_orders_checked`
- [ ] `run_pending_intents` import removed from serve.py
- [ ] All 391 existing tests still pass
