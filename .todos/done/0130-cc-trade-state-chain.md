# CC Trade State Machine: Link ROLL Legs into Evaluation Chain

- **ID:** 0130
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0125, 0127

## Problem

Each ROLL recommendation is evaluated in isolation. When a covered call is rolled (ROLL_OUT, ROLL_UP, ROLL_UP_AND_OUT), a new short call is created at a different strike/expiry. That replacement call may itself be managed (held, BTC'd, or rolled again) before the chain resolves. Currently the evaluator never follows the chain forward: it scores the ROLL decision by looking at the new call's at-expiry state, but it does not connect the replacement call to the subsequent management decisions that affected it. This makes it impossible to measure cumulative CC strategy performance across a multi-leg trade.

## Proposed approach

- Add a `parent_recommendation_id INTEGER` column to `recommendations` (or reuse an existing FK). When the CC agent writes a ROLL recommendation and then writes the management rec for the replacement call, link the replacement rec's `parent_recommendation_id` to the ROLL rec.
- Add a `trade_chain_id TEXT` (UUID or slug) column that is the same across all legs of a single original short-call lifecycle. The SELL_CC rec seeds the chain_id; every ROLL and subsequent management rec inherits it.
- The outcome evaluator, when evaluating the terminal state of a chain, follows `parent_recommendation_id` backwards to aggregate cumulative P&L across all legs.
- Reporting: add a `get_trade_chain(chain_id)` query to `agent_db.py` that returns all recs + outcomes in chain order.
- A chain is "terminal" when the final rec is ALLOW_ASSIGNMENT, BUY_TO_CLOSE, or an expired-OTM HOLD_CALL (i.e., no further management rec exists).

## Touches

- `agent_db.py` — `migrate()` for `parent_recommendation_id`, `trade_chain_id`; `get_trade_chain()` helper
- `agents/cc_agent.py` — set `trade_chain_id` at SELL_CC time; inherit on ROLL and subsequent recs
- `agents/outcome_evaluator.py` — aggregate multi-leg outcomes when evaluating terminal chain state
- `tests/test_lifecycle.py` — seed a 2-leg chain (SELL_CC → ROLL → ALLOW_ASSIGNMENT) and verify cumulative P&L

## Done when

- [ ] `recommendations` has `parent_recommendation_id` and `trade_chain_id` columns
- [ ] SELL_CC rec seeds `trade_chain_id`; ROLL rec sets `parent_recommendation_id` to SELL_CC rec id and inherits `trade_chain_id`
- [ ] `get_trade_chain(chain_id)` returns ordered leg list
- [ ] Outcome evaluator can compute cumulative return across a 2-leg chain (SELL_CC → ROLL → terminal)
- [ ] Lifecycle test verifies chain linkage and cumulative outcome
