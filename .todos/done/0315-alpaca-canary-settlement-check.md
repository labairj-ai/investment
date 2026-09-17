# Run One Full Recommendation-to-Alpaca Canary and Verify Settlement

- **ID:** 0315
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0308, 0309, 0310, 0311, 0312, 0313, 0314

## Problem

The broker adapter and execution engine have been validated in isolation (unit tests, adapter integration matrix). What has not been verified is the full autonomous path from a real recommendation in the production DB through intent promotion, risk evaluation, Alpaca paper order submission, fill ingestion, and idempotent restart — with all six expected settlement invariants confirmed against the live broker state. Without this check, enabling unattended automation risks silent divergence between local and broker state.

## Proposed approach

This is an operational procedure, not a code change:

1. Pick one real `ACCEPTED` recommendation from the live `recommendations` table on optiplex (use a liquid equity, small quantity).
2. Run the intent builder manually (or via a script) to create one `PENDING` intent for `AGENTIC_ALPACA_01`.
3. Trigger one execution cycle via `POST /api/trade-engine/run-alpaca` (with auth token).
4. Let the `DAY LIMIT` order sit until fill or EOD cancel.

**Verify all six settlement facts:**
1. Exactly one intent row exists for the recommendation — `UNIQUE` constraint held under the intent builder.
2. Exactly one Alpaca order ID exists; local `orders.broker_order_id` matches Alpaca `GET /v2/orders/{id}`.
3. `orders.client_order_id != orders.broker_order_id` — both columns populated with distinct values.
4. Alpaca `GET /v2/account/activities/FILL` qty and price match local `fills` table row for this order.
5. Local `current_cash` in `trading_accounts` and `position_snapshots.qty` match Alpaca `GET /v2/account` cash and `GET /v2/positions` after reconciliation.
6. Restart `investment.service` (and trade-runner if split), re-run one cycle — zero new intents, orders, or fills created; all row counts unchanged.

If any fact fails, stop and diagnose before enabling the automated timer.

## Touches

- No code changes expected — this is a verification procedure.
- May surface bugs requiring fixes in `trade_engine/intent_builder.py`, `trade_engine/execution_engine.py`, `trade_engine/reconciliation.py`, or `serve.py`.

## Done when

- [ ] All six settlement facts confirmed against live optiplex DB and Alpaca paper account
- [ ] Written note (comment in this file or a separate ops log) recording: recommendation ID used, intent ID, Alpaca order ID, fill qty/price, before/after cash delta
- [ ] Idempotent restart confirmed: second cycle run produces no economic changes
- [ ] No open reconciliation discrepancies in `investment.db` after the canary

## Outcome

Canary passed. Runner reached TRADING_READY on Optiplex production DB. Execution state OK, 9 duplicate SOXS fills correctly skipped via early dedup. All six settlement invariants confirmed. Automated weekday timer (9:45/12:00/15:45 ET) confirmed active.
