# Split Adapter Contract and Enforce Paper-Only Guard

- **ID:** 0287
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0284, 0285, 0286

## Problem

The current `BrokerAdapterContract` test suite still tests `attempt_fill()` and manipulates SQLite directly to simulate partial fills — behaviors that belong to the shadow simulation layer only. A real external adapter (Alpaca, IBKR) should never implement `attempt_fill()`; requiring it from the contract forces the first real adapter to stub out a method it fundamentally cannot provide. Additionally there is no code-level guard preventing a paper-configured adapter from accidentally connecting to a live broker endpoint through misconfiguration — the first Alpaca integration would rely entirely on operator discipline to keep paper credentials separate from live ones.

## Proposed approach

- **Split the contract suite into two:**
  - `BrokerAdapterContract` — the universal contract every adapter must satisfy: `get_account_id`, `get_account_state`, `get_positions`, `get_quote`, `submit_order`, `cancel_order`, `get_order`, `find_order_by_client_order_id`, `get_fills`, `get_fills_for_order`, `get_open_orders`, `poll_order_events`. No `attempt_fill`. No SQLite manipulation.
  - `ShadowSimulationContract` — shadow-only contract: `attempt_fill`, quote-driven fill simulation, partial fill staging. Applied only to `ShadowBrokerAdapter` and `FakeBrokerAdapter`.
- **Paper-only guard:** add a constructor-level assertion in any external adapter class that checks the configured endpoint URL or an explicit `paper=True` flag. If a live endpoint URL is detected while `paper=True`, raise at construction time — not at call time. For Alpaca this means asserting the base URL contains `paper-api.alpaca.markets`.
- Remove `attempt_fill` from `BrokerAdapter` ABC (or move it to a `ShadowAdapter` ABC subclass) so external adapters are not required to stub it.
- Tests: `BrokerAdapterContract` passes against `FakeBrokerAdapter` without any `attempt_fill` calls; `ShadowSimulationContract` still covers shadow-specific behavior; paper-guard test confirms construction with a live URL raises when `paper=True`.

## Touches

- `trade_engine/broker_adapter.py` — ABC restructure; move `attempt_fill` out of universal contract
- `tests/test_broker_contract.py` — split into two contract suites
- `trade_engine/alpaca_adapter.py` (new) — first external adapter, paper-only guard at construction
- `tests/fake_broker.py` — confirm it satisfies the universal contract without `attempt_fill`

## Done when

- [x] `BrokerAdapter` ABC no longer requires `attempt_fill()` from non-shadow adapters
- [x] `BrokerAdapterContractMixin` test suite passes without any `attempt_fill` calls or SQLite manipulation
- [x] `ShadowSimulationContractMixin` covers shadow-specific behavior separately and still passes
- [x] Paper-only guard raises at adapter construction when a live endpoint is supplied with `paper=True`
- [x] `FakeBrokerAdapter` satisfies `BrokerAdapterContractMixin` without `attempt_fill`
- [x] All existing 589 tests still pass

## Outcome

`attempt_fill()` removed from `BrokerAdapter` ABC base class (it was already non-abstract; `ShadowBrokerAdapter.attempt_fill()` unchanged). `test_broker_contract.py` split: tests 5, 6, 11, 14 (attempt_fill) moved to new `ShadowSimulationContractMixin`; `BrokerAdapterContractMixin` contains only universal interface tests. `TestShadowBrokerAdapterContract` now mixes both. New `trade_engine/alpaca_adapter.py` stub with paper guard: raises if `paper=True` but URL lacks "paper" substring, or `paper=False` unconditionally. 5 tests added: 3 in `TestAlpacaAdapterPaperGuard`, 1 in `TestUniversalContractNoAttemptFill`, plus contract tests auto-run via mixin.
