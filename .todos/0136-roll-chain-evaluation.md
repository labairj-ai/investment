# Implement Multi-Hop Trade-State Chain Evaluation for Rolls

- **ID:** 0136
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

The database schema supports CC trade chains via `trade_chain_id` and `parent_cc_rec_id` on the recommendations table (migration 0130), and SELL_CC recommendations already populate `trade_chain_id`. However, `outcome_evaluator.py` still evaluates each ROLL_OUT / ROLL_UP / ROLL_UP_AND_OUT recommendation in isolation — it models the replacement call's first-order expiry but has no visibility into what actually happened to the replacement call afterward (BTC, another roll, assignment, or OTM expiry). This means a roll that was itself later rolled again, or bought back early, receives an outcome based on an assumed hold-to-expiry path rather than the true terminal state.

## Proposed approach

- Query `agent_db` for all recommendations sharing the same `trade_chain_id`, ordered by `created_at`, to reconstruct the full chain: original SELL_CC → ROLL_* → (optional further ROLL_* or BTC/ALLOW_ASSIGNMENT/HOLD_CALL).
- When evaluating a ROLL_* outcome, check whether a child recommendation exists in the chain (via `parent_cc_rec_id` pointing to the roll rec). If yes, use that child's actual outcome as the terminal state rather than assuming hold-to-new-expiry.
- If no child recommendation exists yet (chain is still open), keep the current first-order approximation and mark the outcome as estimated (`actual_is_estimated = 1`).
- This likely requires a new helper in `agent_db.py` — e.g., `get_chain_recommendations(trade_chain_id)` — and a small refactor of `_compute_cc_management_returns()` to accept an optional chain context dict.

Open questions:
- Should chain-linked outcomes be stored as a single aggregate row or kept as per-hop rows with a chain-level summary?
- How to handle chains that span more than two hops (e.g., roll → roll → assignment)?

## Touches

- `agents/outcome_evaluator.py` — `_compute_cc_management_returns()`, chain context parameter
- `agent_db.py` — new `get_chain_recommendations(trade_chain_id)` query helper
- `tests/test_outcome_evaluator.py` — new test cases for multi-hop scenarios

## Done when

- [ ] A two-hop chain (SELL_CC → ROLL → BTC) produces a roll outcome that reflects the actual BTC price, not a hold-to-expiry assumption
- [ ] An open chain (roll with no subsequent action yet) still produces an estimated outcome without error
- [ ] `python -m pytest tests/test_outcome_evaluator.py -v` passes including new chain tests
- [ ] `python -m pytest tests/` passes with no regressions
