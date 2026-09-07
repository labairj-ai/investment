# Derive ticker/action from Recommendation in Execute API

- **ID:** 0076
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

`POST /api/agents/recommendations/{id}/execute` currently reads `ticker` and `action` from the request body and stores them verbatim. A client could submit `ticker=RIVN, action=SELL_CC` against a recommendation that is actually `EXIT ANET`, and the DB would accept it without error. Because `executed_actions` records are used for outcome evaluation and Decision Quality learning, any corruption here silently poisons the historical dataset.

## Proposed approach

- In `_handle_agent_execute()`, fetch the recommendation row by `rec_id` before inserting.
- Assert the recommendation exists; return 404 otherwise.
- Derive `ticker` and `action` from the fetched recommendation row; ignore any `ticker` or `action` values from the request body entirely.
- Optionally: require the recommendation to be in `status = 'accepted'` before accepting an execution record, or atomically accept + record in a single request (open question: should this be a separate "accept-and-execute" endpoint?).
- Return the recommendation's `ticker` and `action` in the response so the client can confirm what was recorded.
- Add validation that `execution_date` is not in the future and is not before the recommendation's `created_at`.

## Touches

- `serve.py` — `_handle_agent_execute()`
- `tests/test_agent_db.py` or a new `tests/test_serve.py` — test that body ticker/action are ignored

## Done when

- [ ] `ticker` and `action` are always taken from the recommendation row, not the request body
- [ ] 404 returned when recommendation ID does not exist
- [ ] Response includes the derived `ticker` and `action`
- [ ] `execution_date` validated to be ≥ `recommendation.created_at`
- [ ] Test: mismatched ticker/action in body is ignored; recommendation values used
