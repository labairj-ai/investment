# Validate Allowed Decision States on Decision Endpoint

- **ID:** 0077
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

The decision endpoint reads `decision = body.get("decision")` and passes it directly to `close_recommendation(rec_id, status=decision)`. Any string can be written as a recommendation status, including values like `"hacked"`, `"pending"`, or `""`. Because recommendation status is the primary field used to filter which records are eligible for outcome evaluation and preference learning, arbitrary status values corrupt the historical dataset.

## Proposed approach

- Define a constant in `serve.py` (or `agent_db.py`):
  ```python
  VALID_DECISIONS = {"accepted", "rejected", "deferred"}
  ```
- Return HTTP 400 with a clear error message if the submitted `decision` is not in this set.
- Consider also validating that the recommendation is currently `open` before accepting a decision (prevent double-closing).
- Apply the same validation to any other endpoint that can mutate recommendation status.

## Touches

- `serve.py` — decision handler
- `agent_db.py` — optionally move `VALID_DECISIONS` constant here so it is importable by tests
- `tests/test_serve.py` (new or existing) — test invalid decision returns 400

## Done when

- [ ] Decision endpoint rejects any `decision` value not in `{"accepted", "rejected", "deferred"}` with HTTP 400
- [ ] Attempting to close an already-closed recommendation returns an appropriate error
- [ ] Test: invalid decision value returns 400; valid values succeed
