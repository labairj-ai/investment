# Wire Atomic Transaction Helper into Live Execute Endpoint

- **ID:** 0112
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** 0104

## Problem

`record_execution_transaction()` was added to `agent_db.py` in 0104 but `serve.py` still runs the old two-commit sequence: `executed_actions` INSERT commits first, then `cc_positions` sync commits separately. This means a SELL_CC execution can succeed while leaving `cc_positions` empty, or a ROLL can close the old contract without recording the replacement. The error handling in `serve.py` even anticipates these partial-commit scenarios, which confirms the gap exists in the live path.

## Proposed approach

- Replace the multi-step execution sequence in `serve.py`'s `/execute` endpoint with a single call to `record_execution_transaction()`.
- Do the same for the roll multi-leg path (BTC leg + STO leg + `execution_group_id` linking must all land together).
- Remove the compensatory error-handling code that was written to tolerate partial commits.
- Add an integration test that verifies a simulated CC-sync failure rolls back the `executed_actions` row too (failure-injection style, similar to the atomicity tests in `test_agent_db.py`).

## Touches

- `serve.py`
- `tests/test_lifecycle.py` (or new test file for serve-level integration)

## Done when

- [ ] `/execute` endpoint uses `record_execution_transaction()` for all action types
- [ ] Roll multi-leg write (BTC + STO + group) is a single atomic transaction
- [ ] No separate cc_position sync step exists outside the transaction in `serve.py`
- [ ] A test verifies that a CC-sync failure rolls back the execution row
