# Run End-to-End Paper Integration Go/No-Go Matrix

- **ID:** 0296
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0292, 0293, 0294, 0295

## Problem

The engine's safety properties (idempotent fills, crash recovery, no duplicate submissions, atomic audit records) have been verified against `FakeBrokerAdapter` in chaos tests, but never against a real broker. Unknown-fill detection fails closed, so any pre-existing manual trades in a paper account that the engine doesn't know about will halt initialization. There is no verified go/no-go checklist confirming the full engine safety chain holds against the actual Alpaca paper endpoint before unattended execution is enabled.

## Proposed approach

- **Prerequisite**: reset the dedicated paper account to a clean state (no open orders, no positions the engine didn't place). Document the account ID as the expected binding for `AlpacaAdapter(expected_account_id=...)`.
- **Phase 1 — read-only binding**: confirm `get_account_id()` matches `expected_account_id`; confirm balances, positions, and open orders are consistent between the adapter and the paper account UI.
- **Phase 2 — go/no-go matrix** (with `submission_enabled=True`):
  1. Activity stream dropped (kill network mid-cycle) → durable `get_fills()` poll ingests the fill before the next risk decision.
  2. Restart mid-cycle → local and broker order qty, position qty, and cash delta agree exactly after `initialize_trading_session()`.
  3. Crash after `POST /v2/orders` but before ACK → restart finds order via `client_order_id`, no duplicate submission.
  4. Duplicate `BrokerFill` replay → `fills` and `executed_actions` counts unchanged.
  5. No missing `executed_actions` row for any fill (including partial fills).
- **Phase 3 — live order tests**: submit a 1-share DAY LIMIT order at a price that will not fill (well below market) → verify WORKING state; cancel it → verify CANCELLED. Then submit a marketable LIMIT order → verify FILLED state, cash debited, position updated, `executed_actions` written.
- Credentials via `ALPACA_API_KEY` / `ALPACA_API_SECRET` environment variables only; integration tests guarded by `pytest.mark.integration` and skipped in CI unless both vars are set.
- The gate for enabling unattended execution is passing all five matrix points against the real paper account, not a test-count number.

## Touches

- `tests/test_alpaca_integration.py` — new file; `pytest.mark.integration` guard
- `trade_engine/alpaca_adapter.py` — any field-mapping fixes found during integration
- `config/` or `.env.example` — document required environment variables

## Done when

- [ ] Dedicated paper account is clean (no unrecognized positions or open orders)
- [ ] `get_account_id()` matches `expected_account_id`; `initialize_trading_session()` reaches `TRADING_READY`
- [ ] Matrix point 1: activity stream dropped → fill ingested from durable API before next risk decision
- [ ] Matrix point 2: restart mid-cycle → local and broker quantities and cash agree exactly
- [ ] Matrix point 3: crash-after-submit + restart → no duplicate order on the broker side
- [ ] Matrix point 4: duplicate fill replay → `fills` and `executed_actions` row counts unchanged
- [ ] Matrix point 5: every fill (including each leg of a partial fill) has a matching `executed_actions` row
- [ ] 1-share DAY LIMIT order: submit → WORKING → cancel → CANCELLED verified
- [ ] Marketable LIMIT order: submit → FILLED, cash debited, position updated, audit row written
- [ ] Integration tests skip cleanly when credentials are absent
