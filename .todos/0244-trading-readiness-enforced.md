# Enforce Trading Readiness — No Bypass Allowed

- **ID:** 0244
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0242, 0243

## Problem

`run_execution_cycle()` defaults its `trading_state` parameter to `TradingReadyState.TRADING_READY`, meaning callers can skip `initialize_trading_session()` entirely and still submit orders. `process_intent()` is also publicly callable with no readiness gate. The 0242 story also required wiring startup into `serve.py`, which was not done.

## Proposed approach

1. Change `run_execution_cycle()` default from `TRADING_READY` to `INITIALIZING`. Callers must explicitly pass a state obtained from `initialize_trading_session()`.
2. Better: wrap state inside an `ExecutionSession` or `ExecutionEngine` object. `run_execution_cycle()` becomes a method that checks internal state rather than accepting it as a parameter — callers cannot fabricate a ready state.
3. `process_intent()` and `process_new_intents()` should be internal to the session object (or assert readiness before execution).
4. In `serve.py`: call `initialize_trading_session()` at startup; gate the `/run` endpoint on the returned state.
5. Add tests: calling `run_execution_cycle()` without a prior `initialize_trading_session()` returns HALTED.

## Touches

- `trade_engine/execution_engine.py`
- `serve.py`
- `tests/test_trade_engine.py`

## Done when

- [ ] No caller can reach order submission without an explicit `TRADING_READY` state from `initialize_trading_session()`
- [ ] `serve.py` calls `initialize_trading_session()` on startup before enabling the execution endpoint
- [ ] Tests confirm HALTED result when readiness gate is not satisfied
- [ ] `process_intent()` cannot be used to bypass the gate
