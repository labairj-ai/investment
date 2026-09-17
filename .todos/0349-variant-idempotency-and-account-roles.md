# Variant Idempotency and Account Roles

- **ID:** 0349
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0337

## Problem

Two related correctness issues in the challenger execution path:

1. **Variant intents are not idempotent by variant ID.** `build_intent_from_variant()` checks for existing intents via `(account_id, episode_id, decision_origin='PAPER_CHALLENGER', status NOT IN cancelled/rejected/expired)`. If that intent is later rejected for risk reasons, a fresh execution cycle could create a new identical intent for the same variant decision. There is no uniqueness constraint tying `trade_intents` directly to `decision_variants.id`. A rejected challenger variant can re-enter the intent pipeline as if it were a new decision.

2. **ALPACA account-ID string matching is fragile routing.** `build_intent()` routes to the challenger path if `"ALPACA" in account_id.upper()`. This means any future live Alpaca account (e.g., `ALPACA_LIVE_01`) would also receive challenger behavior — executing a different ticker than the accepted recommendation on a live account. Account routing should be based on an explicit role (e.g., `mode='paper_challenger'` on the `trading_accounts` row), not a string fragment in the account ID.

## Proposed approach

**Variant idempotency:**
- Add `decision_variant_id INTEGER REFERENCES decision_variants(id)` column to `trade_intents`
- Add a UNIQUE constraint on `(decision_variant_id)` filtered to non-terminal statuses — or at minimum a check in `build_intent_from_variant()` that queries by `decision_variant_id` rather than `(account_id, episode_id, decision_origin)` combination
- Write `decision_variant_id` on every PAPER_CHALLENGER intent
- Update `_new_cols` migration for the new column

**Account role routing:**
- Add a `role TEXT` column to `trading_accounts` (e.g., `'champion'`, `'paper_challenger'`, `'live'`, `'shadow'`); default NULL (backward compatible)
- `build_intent()` routing: check `trading_accounts.role = 'paper_challenger'` instead of `"ALPACA" in account_id`; fall back to the string check only if the role column is NULL (migration grace period)
- Seed `AGENTIC_ALPACA_01` with `role='paper_challenger'` in `_migrate_trade_engine`

## Touches

- `agent_db.py` — `decision_variant_id INTEGER` column on `trade_intents` in CREATE TABLE + `_new_cols`; `role TEXT` on `trading_accounts` + `_new_cols`; seed `AGENTIC_ALPACA_01.role = 'paper_challenger'`
- `trade_engine/models.py` — `TradeIntent` gains `decision_variant_id: Optional[int]`; `to_db_dict()` + `from_db_row()` updated
- `trade_engine/intent_builder.py` — `build_intent_from_variant()` sets `decision_variant_id`; idempotency check uses `decision_variant_id`; routing logic checks `trading_accounts.role` instead of account_id string
- `tests/` — test that a risk-rejected PAPER_CHALLENGER intent does not produce a duplicate intent on the next cycle; test that a hypothetical `ALPACA_LIVE_01` account without the paper_challenger role gets champion behavior

## Done when

- [ ] `trade_intents.decision_variant_id` populated for every PAPER_CHALLENGER intent
- [ ] A risk-rejected or expired challenger intent for a given `decision_variant_id` cannot be re-created as a fresh pending intent on re-run
- [ ] Routing to the challenger path uses `trading_accounts.role = 'paper_challenger'` (not string-matching on account_id)
- [ ] A future `ALPACA_LIVE_01` account without the paper_challenger role receives champion behavior
- [ ] `python -m pytest tests/` passes with no regressions
