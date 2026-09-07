# Atomic CC Execution ↔ cc_positions Sync

- **ID:** 0005
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** none

## Problem

Recording a SELL_CC execution through `_handle_agent_execute()` writes to `executed_actions` but does not create or update a `cc_positions` record. Conversely, managing CC positions through the positions endpoint is entirely separate from the execution ledger. This means the agent's execution ledger and the CC management agent's position view can disagree: the ledger says a call was sold, but the CC management agent sees no open position and may re-recommend the same SELL_CC.

## Proposed approach

- In `_handle_agent_execute()`, after writing to `executed_actions`, branch on action:
  - `SELL_CC` → atomically INSERT a `cc_positions` row (ticker, strike, expiry, premium, contracts, opened_date, status='open', source='agent_execution') in the same DB transaction
  - `BUY_TO_CLOSE` → atomically UPDATE the matching `cc_positions` row to status='closed', set close_type and net_premium
  - `ALLOW_ASSIGNMENT` → UPDATE to status='assigned'
  - `ROLL_OUT` / `ROLL_UP` / `ROLL_UP_AND_OUT` → close old leg + open new leg in one transaction
- Deduplicate: if a `cc_positions` row already exists for (ticker, strike, expiry) with status='open', skip the insert and log a warning rather than creating a duplicate
- Wrap both writes in a single `BEGIN … COMMIT` so partial failures leave neither table inconsistent
- The existing manual `cc_positions` endpoint remains available for positions entered outside the agent system

## Touches

- `serve.py` (`_handle_agent_execute`)
- `agent_db.py` (may need `insert_cc_position_from_execution`, `close_cc_position_from_execution` helpers)

## Done when

- [ ] Executing a SELL_CC recommendation via the API creates a matching `cc_positions` row in the same transaction
- [ ] Executing BUY_TO_CLOSE closes the matching `cc_positions` row in the same transaction
- [ ] Both writes are atomic: a DB error on either write rolls back both
- [ ] Duplicate SELL_CC execution (same ticker/strike/expiry already open) is rejected or skipped with a clear error, not silently duplicated
- [ ] Unit test: `POST /api/agents/execute` with SELL_CC → assert `cc_positions` row exists with correct fields
- [ ] Unit test: `POST /api/agents/execute` with BUY_TO_CLOSE → assert matching `cc_positions` row is closed
- [ ] Unit test: partial DB failure → neither `executed_actions` nor `cc_positions` is written (transaction rollback)
- [ ] Manual web check: executing a SELL_CC through the decision queue causes the CC positions panel to show the new open position without a manual page reload
