# Submission and Fill Safety Cleanup: Quote Sanity, Overfill, ExecutionSession

- **ID:** 0262
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0261, 0258

## Problem

Four safety gaps that must be closed before connecting a real paper-broker adapter:

**1. Quote gate missing explicit bid/ask sanity checks.**
The 0251 acceptance criteria include:
> "bid <= 0, ask <= 0, bid > ask each independently block submission."

The current code reaches the spread check via:
```python
if bquote.ask > 0:
    spread_pct = (ask - bid) / ask
```
A quote with `bid=101, ask=99` produces a negative spread that is below `max_spread_pct` and therefore _passes_ the gate. A quote with `ask <= 0` skips the spread check entirely and may still proceed to submission. These cases must be caught with explicit guards before the spread calculation:
```python
if bquote.bid <= 0 or bquote.ask <= 0:
    return QUOTE_REJECTED (reason: "non-positive bid/ask")
if bquote.bid > bquote.ask:
    return QUOTE_REJECTED (reason: "bid exceeds ask")
```
`ShadowBroker` already has these guards internally, but the intent is for `process_intent()` to reject bad quotes before any broker interaction.

**2. Overfill detection is absent.**
`apply_broker_fill()` applies fill quantities without checking whether the reported fill exceeds the order's remaining quantity. A broker reporting a fill of 10 shares on a 1-share order will silently add 10 shares to the position and debit 10 shares' worth of cash. At minimum, log a warning when `fill_qty > (order.quantity - order.fill_qty)` and halt if the overfill is material (> 1 share or > 1% of order quantity).

**3. Impossible sells are silently clamped.**
Position mutation for a SELL fill currently appears to do `max(0, old_qty - fill_qty)` rather than asserting that enough shares are held to cover the fill. Selling shares the account does not hold is a real risk for an autonomous system; the correct behavior is to halt and quarantine, not to silently floor at zero.

**4. Readiness is caller-supplied and bypassable.**
`run_execution_cycle()` accepts `trading_state=TradingReadyState.TRADING_READY` from its caller, and `process_intent()` accepts a `conn` and `broker` with no readiness check at all. A caller can bypass `initialize_trading_session()` and reconciliation entirely. The 0254 story (ExecutionSession) proposed the fix:

```python
session = ExecutionSession(account_id, conn, broker)
session.initialize()   # reconciliation; returns READY or raises
session.process_intent(intent_id)
session.run_cycle()
```

`TRADING_READY` should be internal session state, not a caller-supplied assertion. This story delivers the minimum viable version: at least `process_intent()` and `run_execution_cycle()` must check that initialization has been run and was successful before processing any order.

## Proposed approach

1. **Explicit bid/ask sanity checks** at the top of the quote gate in `process_intent()`, before the spread calculation. Add corresponding parameterized tests that assert `submit_order.call_count == 0` for each of: `bid=0`, `ask=0`, `bid<0`, `ask<0`, `bid>ask`.

2. **Overfill guard in `apply_broker_fill()`.** After fetching the order row, compute `remaining = order.quantity - order.fill_qty`. If `fill.qty > remaining + epsilon` (allow float tolerance), log a warning and either:
   - For small overfills (rounding): apply and log.
   - For material overfills (> 1%): raise `OverfillError`, triggering a halt.

3. **Impossible sell guard in position mutation.** Before executing a SELL fill's position update, assert `current_position.qty >= fill.qty`. If not, raise `ImpossibleSellError` and halt rather than flooring at zero.

4. **ExecutionSession minimum viable shell (from 0254).** Introduce an `ExecutionSession` class in `execution_engine.py` that:
   - Owns `account_id`, `conn`, `broker`, and an `_initialized: bool` flag.
   - `initialize()` calls `initialize_trading_session()` and stores the result; raises `SessionNotReadyError` if not TRADING_READY.
   - `process_intent()`, `process_open_orders()`, and `run_execution_cycle()` as methods that assert `_initialized` before proceeding.
   - The existing module-level functions are preserved for backward compatibility but internally delegate to an implicit session, or are deprecated with a warning.
   
   This can be done incrementally: the flag-check behavior is the minimum; the full session object from 0254 can be elaborated later.

5. **Revisit Decimal money domain (0258 scope).** After the above, review which boundary types still use float. This story's scope: `BrokerOrderEvent`, `BrokerAccountState`, and order-submission paths. Full 0258 scope covers `BrokerFill`, `BrokerPosition`, and the SQLite adapter. Either land them together or confirm 0258 is addressed separately before marking 0262 done.

## Touches

- `trade_engine/execution_engine.py` — quote sanity checks, overfill guard, impossible sell guard, `ExecutionSession`
- `trade_engine/models.py` — `OverfillError`, `ImpossibleSellError`, `SessionNotReadyError` exceptions
- `tests/test_trade_engine.py` — parameterized bad-quote tests, overfill test, impossible sell test, ExecutionSession readiness test
- `tests/test_chaos.py` — overfill and impossible-sell chaos scenarios

## Done when

- [x] `process_intent()` explicitly checks `bid > 0`, `ask > 0`, and `bid <= ask` before any spread calculation; each independently returns `QUOTE_REJECTED` with a descriptive reason
- [x] Tests: `bid=0`, `ask=0`, `bid<0`, `bid>ask` each assert no order submitted (TestQuoteSanityChecks)
- [x] `apply_broker_fill()` detects when `fill.qty > order.remaining_qty` and halts (raises OverfillError) for material overfills
- [x] SELL fill position mutation asserts sufficient shares held; raises ImpossibleSellError instead of flooring at zero
- [x] `ExecutionSession` guards `process_intent()` and `run_execution_cycle()` — SessionNotReadyError raised if `initialize()` not called
- [x] Test: calling `process_intent()` and `run_cycle()` without initialize raises `SessionNotReadyError`
- [ ] Decimal money domain boundaries (BrokerOrderEvent, BrokerAccountState, submission paths) — deferred to 0258 scope
- [x] 520+ existing tests continue to pass

## Outcome

- `process_intent()` quote gate: explicit `bid <= 0 or ask <= 0 or bid > ask` check returns `QUOTE_REJECTED` before spread calculation. Inverted spread (bid=101, ask=99) no longer slips through.
- `apply_broker_fill()`: `OverfillError` if `fill.qty > remaining + 1e-6`; `ImpossibleSellError` if sell qty > held position; `UnknownFillError` if order not in local DB.
- `ExecutionSession` class added: owns `_initialized` flag; `initialize()` calls `initialize_trading_session()` and raises `SessionNotReadyError` if not TRADING_READY; `process_intent()`, `process_open_orders()`, `run_cycle()` assert initialized.
- `SessionNotReadyError` exception class added.
- `TestExecutionSession` added (uninitialized guards, successful initialize → TRADING_READY).
- `TestQuoteSanityChecks` added (bid=0, ask=0, bid<0, bid>ask each → QUOTE_REJECTED, 0 orders).
- 536 tests pass.
