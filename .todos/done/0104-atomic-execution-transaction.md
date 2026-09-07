# Make All Execution + CC State Updates One SQLite Transaction

- **ID:** 0104
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** none

## Problem

`insert_executed_action()` and `insert_cc_position_from_execution()` each open their own SQLite connection and commit immediately. `serve.py` catches CC sync errors only after the execution row has already been persisted, so a crash between the two writes leaves `executed_actions` showing a sold call with no corresponding `cc_positions` row. ROLL is worse: the BTC leg commits first, then the STO leg, then `execution_group_id` is set in a third write — if any step after the first fails, the fill_id on the BTC leg prevents a retry from completing the missing STO leg. The 0098/0101 work added the right concepts but not transactional integrity.

## Proposed approach

- Create `record_execution_transaction(rec_id, body, action, conn=None)` in `agent_db.py` (or a new `execution_tx.py`) that takes a single connection, runs `BEGIN IMMEDIATE`, and does all writes before a single `COMMIT`; any exception triggers `ROLLBACK`.
- Branch internally on action:
  - `SELL_CC` → insert executed_action + insert cc_position atomically
  - `BUY_TO_CLOSE` → insert executed_action + close cc_position atomically
  - `ALLOW_ASSIGNMENT` → insert executed_action + close cc_position atomically
  - `ROLL_*` → insert BTC leg + STO leg + set execution_group_id on both + close old cc_position + create new cc_position — all in one transaction
  - all others → insert executed_action only
- `serve.py` execute endpoint calls only this function; remove the sequential multi-call pattern and the try/except CC sync fallback.
- The connection should be passed in by the caller so tests can use an in-memory DB.

## Touches

- `agent_db.py` — new `record_execution_transaction()` (or `execution_tx.py`)
- `serve.py` — `/api/agents/recommendations/{id}/execute` endpoint; remove sequential calls + CC sync try/except
- `tests/test_agent_db.py` or new `tests/test_execution_tx.py` — atomicity tests

## Done when

- [ ] A single `record_execution_transaction()` function exists that wraps all writes in one `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`.
- [ ] Unit test: SELL_CC transaction where cc_positions insert is forced to raise — asserts that `executed_actions` row is also absent (full rollback).
- [ ] Unit test: ROLL transaction where STO insert is forced to raise — asserts BTC leg is also absent and cc_positions is unchanged.
- [ ] Unit test: successful SELL_CC → exactly one `executed_actions` row and exactly one `cc_positions` row; successful ROLL → exactly two `executed_actions` rows with matching `execution_group_id`, old cc_position closed, new cc_position open.
- [ ] `serve.py` execute endpoint no longer contains a try/except that allows a partial-success state for CC sync.
- [ ] Full pytest suite passes with no regressions.
- [ ] Manual end-to-end: POST a SELL_CC execution to the running optiplex server, verify both `executed_actions` and `cc_positions` rows exist; POST a ROLL, verify both legs present with matching group ID and cc_positions updated correctly.
