# Make Recommendation-to-Intent Promotion Idempotent

- **ID:** 0314
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0311

## Problem

`trade_intents` has a `recommendation_id` column but no `UNIQUE` constraint on `(account_id, recommendation_id)`. If the intent builder runs twice against the same `ACCEPTED` recommendation — due to a scheduler retry, a double-fire, or a restart — it creates multiple `PENDING` intents. Each can independently pass risk checks and reach `broker.submit_order()`. The broker's `client_order_id` idempotency gate exists at the order layer, not the intent layer, so duplicate intents produce duplicate orders with distinct `client_order_id` values and are not caught.

## Proposed approach

1. **Schema constraint:** add `CREATE UNIQUE INDEX IF NOT EXISTS idx_intents_account_rec ON trade_intents (account_id, recommendation_id)` in `agent_db._migrate_trade_engine()`. Open question: should the index be `(account_id, recommendation_id)` or `(account_id, recommendation_id, strategy_config_hash)` if multiple strategies are ever expected to act on the same recommendation for different accounts?
2. **Intent builder:** change plain `INSERT INTO trade_intents` to `INSERT OR IGNORE` and check `rowcount` after; log and skip if the intent already exists for this account+recommendation.
3. **Promotion eligibility contract** — document and enforce these checks before the INSERT:
   - `instrument_type == EQUITY`
   - `side in {BUY, SELL}`
   - `valid_until` not expired at promotion time
   - `quantity` and `limit_price` present and positive
   - recommendation `status == ACCEPTED` and not previously routed to this account (enforced by the UNIQUE index)
4. Add a migration to apply the index to the live optiplex DB.

## Touches

- `agent_db.py` — `_migrate_trade_engine()`: add unique index
- `trade_engine/intent_builder.py` — `INSERT OR IGNORE`, eligibility checks, logging
- `tests/test_trade_engine.py` — duplicate-promotion test: second call for same rec is a no-op

## Done when

- [x] `UNIQUE(account_id, recommendation_id)` index exists in `trade_intents` on both dev and optiplex DB
- [x] Calling the intent builder twice with the same ACCEPTED recommendation creates exactly one intent
- [x] All promotion eligibility checks fire before INSERT and produce a logged skip, not a runtime error
- [x] Existing intent builder tests still pass; new duplicate-promotion test added

## Outcome

INSERT OR IGNORE on trade_intents with UNIQUE INDEX on (account_id, recommendation_id WHERE recommendation_id IS NOT NULL). Pre-checks for ACCEPTED status, positive quantity/price, and supported actions.
