# Prove External Fill Ownership Before BROKER_EXTERNAL Classification

- **ID:** 0569
- **Status:** backlog
- **Created:** 2026-09-22
- **Priority:** high
- **Depends:** 0568

## Problem

`apply_broker_fill()` currently assumes that any fill whose `broker_order_id` cannot be resolved to a local order is an external fill (BROKER_EXTERNAL). But a legitimate engine-owned fill can be temporarily unresolvable during the PENDING_SUBMIT crash-recovery window: the engine wrote a PENDING_SUBMIT order with a `client_order_id`, Alpaca filled it, but the process crashed before `broker_order_id` was saved locally. When the runner restarts and fetches fills before reconciliation has recovered that order, the fill has a `broker_order_id` that resolves to nothing. The current code economically applies it as BROKER_EXTERNAL with `order_id=NULL`. Later, reconciliation recovers the broker order via `client_order_id`, but when it tries to apply the authoritative fill again, early dedup returns ALREADY_APPLIED — the fill row remains `order_id=NULL` and the local order never receives its fill quantity or state transition. This silently weakens the crash-safety model introduced in 0253/0270/0277.

## Proposed approach

Change the rule from "unresolved → BROKER_EXTERNAL" to "unresolved → attempt broker-order identity recovery → only then classify external."

**Preferred approach — recover PENDING_SUBMIT lineage before importing fills:**
- In `initialize_trading_session()`, before the fill import loop, resolve all PENDING_SUBMIT orders against the broker by `client_order_id` (as reconciliation section 3c already does). This ensures fills encounter a resolved order and the crash-recovery path works as designed.

**Fallback approach — broker-order lookup inside `apply_broker_fill()`:**
- When `resolve_local_order_id()` returns None and `broker_order_id` is present, call `broker.get_order(broker_order_id)` to retrieve the order's `client_order_id`.
- Retry `resolve_local_order_id` using that `client_order_id`.
- If the `client_order_id` matches the engine namespace (`AGENTIC_ALPACA_01:<intent_id>`) but local lineage still cannot be found, quarantine/halt — do not externalize.
- Only classify BROKER_EXTERNAL if the broker order is positively shown not to belong to the engine (i.e., `client_order_id` is absent or does not match the engine namespace).

**Critical regression test to add:**
1. Seed a PENDING_SUBMIT order with `client_order_id` set; do not assign `broker_order_id`.
2. Stage an Alpaca fill referencing that order's `broker_order_id` (simulating a crash before broker_order_id was written back).
3. Run `initialize_trading_session()` with a broker that returns the fill.
4. Assert the fill is NOT classified BROKER_EXTERNAL.
5. Assert that after reconciliation completes, the local order receives its fill and reaches FILLED state.

## Touches

- `trade_engine/execution_engine.py` — `apply_broker_fill()` BROKER_EXTERNAL path or `initialize_trading_session()` pre-fill reconciliation step
- `trade_engine/broker_adapter.py` — `BrokerAdapter` ABC may need `get_order()` accessible from `apply_broker_fill()`
- `tests/test_chaos.py` — PENDING_SUBMIT crash + fill + restart regression test

## Done when

- [ ] A fill whose broker_order_id belongs to a PENDING_SUBMIT order is not classified BROKER_EXTERNAL under any restart ordering
- [ ] The regression test (PENDING_SUBMIT crash → fill before broker_order_id saved → restart → reconcile → FILLED) passes
- [ ] An external fill whose broker order carries no engine-namespace client_order_id is still correctly classified BROKER_EXTERNAL
- [ ] No existing chaos tests regress
