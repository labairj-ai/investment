# Enforce Variant Idempotency with Hard DB Constraint

- **ID:** 0352
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0349

## Problem

`build_intent_from_variant()` queries for existing intents using `status NOT IN (CANCELLED, REJECTED, EXPIRED)`. This means a REJECTED or EXPIRED variant intent is invisible to the idempotency check, and a fresh execution cycle will create a new intent for the same `decision_variant_id` — the exact outcome the todo was meant to prevent. There is also no unique index on `decision_variant_id` in the schema; the existing unique index covers `(account_id, recommendation_id)` but challenger intents deliberately use `recommendation_id=NULL`, so that index provides no protection. The current implementation effectively satisfies the opposite of its stated acceptance criterion.

## Proposed approach

- Add `CREATE UNIQUE INDEX IF NOT EXISTS idx_intent_per_variant ON trade_intents(account_id, decision_variant_id) WHERE decision_variant_id IS NOT NULL` in `agent_db.py` (after `_new_cols`)
- Rewrite the idempotency check in `build_intent_from_variant()` to query ALL statuses for the given `decision_variant_id` (no status filter)
- If an existing intent row is found regardless of status:
  - If terminal (CANCELLED, REJECTED, EXPIRED, FILLED): return `None` with a log message — this variant decision is done, do not retry as a new decision
  - If non-terminal (PENDING, SUBMITTED): return the existing intent
- This makes a variant a single, immutable decision: if it was ever rejected, it cannot be re-entered without a new variant row

## Touches

- `agent_db.py` — add unique partial index on `(account_id, decision_variant_id)` where not null
- `trade_engine/intent_builder.py` — `build_intent_from_variant()` idempotency query: remove status filter; branch on terminal vs non-terminal
- `tests/test_calibration.py` or `tests/test_trade_engine.py` — test that a REJECTED variant produces `None` on re-run (not a new intent); test that the unique index prevents duplicate rows

## Done when

- [ ] `CREATE UNIQUE INDEX` on `(account_id, decision_variant_id) WHERE decision_variant_id IS NOT NULL` exists in the schema
- [ ] `build_intent_from_variant()` queries all statuses; returns `None` for any terminal existing intent
- [ ] A REJECTED variant intent cannot become a new PENDING intent on re-run
- [ ] Test: seed variant, create intent, mark REJECTED, re-run builder → `None` returned, no new row
- [ ] `python -m pytest tests/` passes with no regressions
