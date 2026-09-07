# Action-Specific Execution Validation

- **ID:** 0092
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

`_handle_agent_execute()` in `serve.py` accepts any numeric values for `quantity`, `execution_price`, `strike`, `premium`, `contracts`, `execution_fraction` without action-specific validation. Accidental double-submission creates duplicate `executed_actions` rows. The history being built will inform the Decision Quality model; bad data entered now will corrupt future learning.

## Proposed approach

Add validation in `_handle_agent_execute()` before calling `agent_db.insert_executed_action()`:

- **General (all actions):**
  - Recommendation status must be `"accepted"` (not open/rejected/deferred); return 409 if not
  - `execution_date <= today`; return 400 if future date

- **EXIT / TRIM:**
  - `quantity > 0` and `execution_price > 0`; return 400 if missing/invalid
  - `quantity <= position_shares_before` when `position_shares_before` is provided
  - `0 < execution_fraction <= 1.0`

- **SELL_CC:**
  - `contracts >= 1` and `strike > 0` and `premium > 0`; return 400 if missing/invalid
  - `expiration >= execution_date`; return 400 if expired
  - `contracts * 100 <= position_shares_before` when provided (can't sell more calls than covered shares)

- **Idempotency:**
  - Accept optional `fill_id` string in request body
  - Store `fill_id` in a new `fill_id TEXT UNIQUE` column on `executed_actions`
  - Return 409 with existing `executed_action_id` if `fill_id` already exists (duplicate prevention)

## Touches

- `serve.py` — `_handle_agent_execute()` — add validation block before DB write
- `agent_db.py` — `insert_executed_action()` — add `fill_id` parameter; `migrate()` adds column
- `tests/test_lifecycle.py` — add: SELL_CC with contracts*100 > shares → 400; duplicate fill_id → 409

## Done when

- [ ] TRIM with `quantity > position_shares_before` returns 400
- [ ] SELL_CC with expired expiration returns 400
- [ ] SELL_CC with `contracts*100 > covered_shares` returns 400
- [ ] Duplicate `fill_id` submission returns 409 with existing action ID
- [ ] Execution against a non-accepted recommendation returns 409
