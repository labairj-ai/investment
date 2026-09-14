# Run End-to-End Paper Integration Go/No-Go Matrix

- **ID:** 0296
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0292, 0293, 0294, 0295

## Problem

The engine's safety properties (idempotent fills, crash recovery, no duplicate submissions, atomic audit records) have been verified against `FakeBrokerAdapter` in chaos tests, but never against a real broker. Unknown-fill detection fails closed, so any pre-existing manual trades in a paper account that the engine doesn't know about will halt initialization. There is no verified go/no-go checklist confirming the full engine safety chain holds against the actual Alpaca paper endpoint before unattended execution is enabled.

## Proposed approach

Execute in this exact order — do not skip phases:

**Phase 1 — read-only (no submission_enabled)**
Verify account binding, cash/NAV, positions, open orders, historical fills, AAPL quote, and `initialize_trading_session()` → `TRADING_READY`. Compare key values manually against the Alpaca paper UI once.

**Phase 2 — 1-share non-marketable limit/cancel**
Submit a 1-share DAY LIMIT order priced well below market (will not fill). Verify real `broker_order_id` returned, `find_order_by_client_order_id()` resolves it, order reaches WORKING state, cancel issues 204, polling detects CANCELLED terminal state.

**Phase 3 — 1-share marketable LIMIT fill (economic settlement)**
Submit a marketable LIMIT order. Assert: real Alpaca activity ID becomes local `fill_id`; exactly one fill row; one `executed_actions` row; position quantity updated; cash debited by `qty × price`. Restart immediately after; confirm fill replay is idempotent (row counts unchanged).

**Phase 4 — hostile matrix**
1. Activity stream dropped (kill network mid-cycle) → durable `get_fills()` poll ingests fill before next risk decision.
2. Restart with an order that filled while down → `initialize_trading_session()` ingests fills, reaches `TRADING_READY` without duplicate submission.
3. Crash after `POST /v2/orders` but before ACK → restart finds order via `client_order_id`, no duplicate submission.
4. Duplicate `BrokerFill` replay → `fills` and `executed_actions` row counts unchanged.
5. Every fill (including each leg of a partial fill if Alpaca paper produces one) has a matching `executed_actions` row.

Add 0305 and 0306 during this work — they are small enough not to block Phase 1 or 2 but must be in before Phase 4.

**Prerequisite**: reset dedicated paper account to clean state (no open orders, no unrecognized positions). Document account ID as `ALPACA_EXPECTED_ACCOUNT_ID`.

## Touches

- `tests/test_alpaca_integration.py` — expand beyond scaffold; add Phase 2–4 tests
- `trade_engine/alpaca_adapter.py` — any field-mapping bugs found during live runs
- `trade_engine/reconciliation.py` — 0305/0306 fixes applied before Phase 4

## Done when

- [ ] Paper account is clean; `ALPACA_EXPECTED_ACCOUNT_ID` documented
- [ ] Phase 1: `get_account_id()` matches expected; `initialize_trading_session()` → `TRADING_READY`; balances match UI
- [ ] Phase 2: 1-share non-marketable order → WORKING → cancel → CANCELLED; `client_order_id` lookup works
- [ ] Phase 3: marketable fill → real activity ID as `fill_id`; cash/position/audit correct; restart replay is idempotent
- [ ] Phase 4, point 1: activity stream dropped → fill ingested from durable API before next risk decision
- [ ] Phase 4, point 2: restart after fill while down → `TRADING_READY`, no duplicate order
- [ ] Phase 4, point 3: crash-after-submit + restart → no duplicate order on broker
- [ ] Phase 4, point 4: duplicate fill replay → row counts unchanged
- [ ] Phase 4, point 5: every fill leg has a matching `executed_actions` row
- [ ] 0305 (terminal lookup uncertainty) resolved before Phase 4
- [ ] 0306 (fill completeness assertion) resolved before Phase 4
- [x] Integration tests skip cleanly when credentials are absent

## Progress

`tests/test_alpaca_integration.py` scaffolded (0294/0295). Submission gated by
`ALPACA_INTEGRATION_SUBMIT=1`; account binding gated by `ALPACA_EXPECTED_ACCOUNT_ID`.
Adapter hardened through 0297–0304 (commit 7f398ca). Ready to begin Phase 1.
