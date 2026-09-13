# Introduce ExecutionSession to Own Trading State

- **ID:** 0254
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0251, 0252, 0253

## Problem

`run_execution_cycle()` now requires an explicit `TradingReadyState`, which is an
improvement, but any caller can trivially bypass the gate by passing
`trading_state=TradingReadyState.TRADING_READY`. `process_intent()` remains a public
function that is callable with no readiness check at all. There is nothing in the type
system or the runtime that prevents a future caller — or a test — from submitting orders
without going through `initialize_trading_session()` and reconciliation first.

The fix is an `ExecutionSession` object whose `initialize()` method owns the state
machine transition and whose execution methods (`run_cycle()`, etc.) are only reachable
through a successfully initialised session handle, not through a free function with a
side-channel parameter.

## Proposed approach

1. Create `class ExecutionSession` in `execution_engine.py` (or a new
   `trade_engine/session.py`):
   - Constructor: takes `account_id`, `conn`, `broker: BrokerAdapter`.
   - `initialize() -> TradingReadyState`: runs `initialize_trading_session()` logic
     internally. Returns the state. Stores `_ready` flag; only `TRADING_READY` sets it.
   - `run_cycle() -> ExecutionResult`: asserts `_ready` before delegating; raises if
     called on an uninitialised or halted session.
   - `_process_intent()` and `_process_open_orders()` become private methods on the
     session, not module-level functions.
2. Update `serve.py` to instantiate and initialise an `ExecutionSession` per cycle.
3. Keep the existing module-level functions as deprecated shims (for test compatibility)
   that construct a session internally — or update tests to use the session API.
4. The guard in `_process_intent()` should not rely on a caller-supplied state parameter;
   it should read `self._ready`.

Open question: should `ExecutionSession` be stateful across multiple cycles (long-lived)
or reconstructed per cycle? Long-lived is more natural for reconnect/heartbeat, but
per-cycle is simpler and consistent with the current architecture.

## Touches

- `trade_engine/execution_engine.py`
- `serve.py`
- `tests/test_trade_engine.py`

## Done when

- [ ] `ExecutionSession` class exists with `initialize()` and `run_cycle()` methods
- [ ] `run_cycle()` raises or is a no-op if `initialize()` returned non-TRADING_READY
- [ ] No external caller can reach `_process_intent()` / `_process_open_orders()` directly
- [ ] Callers cannot supply `trading_state=TRADING_READY` to bypass initialisation
- [ ] `serve.py` constructs and initialises a session before calling `run_cycle()`
- [ ] Existing test coverage remains intact (shims or updated call sites)
- [ ] All tests pass
