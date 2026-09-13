# Build Hostile FakeBrokerAdapter for Chaos Testing

- **ID:** 0249
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0248

## Problem

The current contract test suite verifies happy-path behavior only. Before a real adapter is written, the system must demonstrate correct behavior under the failure modes that real brokers actually produce: delayed ACKs, partial fills, duplicate fill events, out-of-order events, submission timeouts, stale quotes, cancellation/fill races, unknown broker orders on reconnect, and crash-at-every-meaningful-point. Without a hostile test adapter, architectural problems will be discovered against a real broker API with real money.

## Proposed approach

Build `tests/fake_broker.py` with a `FakeBrokerAdapter(BrokerAdapter)` whose behavior is configurable per-scenario:

- `delay_ack=True` — `place_order()` returns acknowledgment after N calls (simulates slow network)
- `duplicate_fills=True` — `poll_order_events()` returns the same fill event twice
- `out_of_order_fills=True` — deliver fill events in reverse chronological order
- `cancel_race=True` — deliver FILLED event simultaneously with cancel ACK
- `submit_timeout=True` — `place_order()` raises `TimeoutError`
- `crash_after_submit=True` — succeeds once, then raises on second call (simulates crash-after-ack)
- `unknown_broker_orders` — `get_open_orders()` returns orders not in local DB
- `position_mismatch` — `get_positions()` returns qty different from local state
- `stale_quote=True` — `get_quote()` returns quote with `retrieved_at` > stale threshold

Scenario tests in `tests/test_chaos.py`:
- Duplicate fill: account debited once, not twice
- Submit timeout + restart: no duplicate order via `client_order_id`
- Cancel/fill race: order ends in FILLED (not CANCELLED), cash correct
- Out-of-order fills: final state matches total fill qty regardless of event order
- Unknown broker order on reconnect: detected and imported, not re-submitted

## Touches

- `tests/fake_broker.py` — new `FakeBrokerAdapter`
- `tests/test_chaos.py` — new chaos scenario tests
- `trade_engine/broker_types.py` — `BrokerOrderEvent` (depends on 0248)

## Done when

- [ ] `FakeBrokerAdapter` is configurable for all failure modes listed above
- [ ] All chaos scenarios in `test_chaos.py` pass
- [ ] Duplicate fill produces correct account state (one debit)
- [ ] Crash-after-submit + restart produces no duplicate order
- [ ] Cancel/fill race resolves to correct final order and cash state
