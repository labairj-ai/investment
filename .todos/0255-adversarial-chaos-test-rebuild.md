# Rebuild Chaos Tests as True Adversarial Event-Driven Tests

- **ID:** 0255
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0252, 0253

## Problem

The existing `tests/test_chaos.py` suite (0249) gives false confidence. The
duplicate-fill test calls `broker.attempt_fill()` manually once and never routes a
second `BrokerOrderEvent` through `apply_broker_fill()`, so it doesn't prove idempotency
under replay. The cancel/fill race test explicitly notes that `poll_order_events()` is
not called, then accepts zero *or* one fill as valid — that isn't proving race resolution.
The timeout/restart test throws `TimeoutError` before the fake broker creates any order,
so the genuinely dangerous scenario (broker accepted the order, response was lost) is
never exercised.

The suite needs to be rebuilt so every test actually exercises the failure path it claims
to validate, and so `apply_broker_fill()` and the event-ingestion pipeline are the
system under test — not the lower-level shadow helpers.

## Proposed approach

1. **Duplicate fill via ingestion** — produce two identical `BrokerOrderEvent` objects,
   pipe both through the event-ingestion loop (calling `apply_broker_fill()` twice),
   then assert fills count == 1, cash debited once, position incremented once.
2. **Cancel/fill race** — produce a `FILLED` event and a `CANCELLED` event for the same
   order in the same batch; process both via the ingestion loop; assert the order ends in
   `FILLED` and cash/positions reflect exactly one fill.
3. **Out-of-order partial fills** — produce two `PARTIALLY_FILLED` events with fill qty
   1 each, deliver them in reverse timestamp order; assert order ends `FILLED`, total
   fill qty == 2, cash debited for 2 shares.
4. **Accepted-but-response-lost restart** — use the updated `FakeBrokerAdapter` (0253)
   that internally creates a broker order then throws `TimeoutError`; simulate restart by
   calling `initialize_trading_session()` again; assert reconciliation finds the
   broker-side order via `client_order_id` and does NOT submit a second order.
5. **Retrieval failure halts** — independently simulate `get_positions()`, `get_open_orders()`,
   `get_fills()`, and `get_broker_account()` each raising an exception; assert each
   independently causes `initialize_trading_session()` to return `HALTED`.
6. **Position mismatch blocks** — existing test is correct in intent; verify it still
   works after 0252 and 0253 changes.
7. **Stale quote no-fill** — reroute through the updated quote gate (0251); verify order
   remains WORKING and submit is not called.

Each test must use the production ingestion code paths, not shadow-broker helpers, as the
system under test.

## Touches

- `tests/test_chaos.py` — full rewrite of most test classes
- `tests/fake_broker.py` — update `submit_timeout` to model accepted-but-lost scenario
- Depends on `apply_broker_fill()` idempotency (0252) and PENDING_SUBMIT state (0253)
  being implemented first, otherwise the ingestion tests will fail for the wrong reasons

## Done when

- [ ] Duplicate `BrokerOrderEvent` flows through `apply_broker_fill()` twice; fills == 1, cash/position debited once
- [ ] Cancel + fill in same batch → order `FILLED`, correct cash, no double-debit
- [ ] Out-of-order partial fills → order `FILLED`, total qty correct
- [ ] Accepted-but-lost restart → `broker.submit_order` called exactly once across both attempts
- [ ] Each of `get_positions`, `get_open_orders`, `get_fills`, `get_broker_account` failure independently → `HALTED`
- [ ] No chaos test uses `attempt_fill()` or shadow-broker internals as the primary assertion path
- [ ] All 515+ existing tests continue to pass
