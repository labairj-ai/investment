# Outcome Evaluator: Recursive Multi-Hop Roll Chain Attribution

- **ID:** 0180
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** low
- **Depends:** none

## Problem

The Outcome Evaluator handles ROLL action outcomes one child deep. When a ROLL produces another ROLL child, the evaluator marks the chain as still open/estimated rather than recursively resolving it. This means a ROLL → ROLL → BUY_TO_CLOSE chain never has a fully-attributed realized outcome — it stays "estimated" indefinitely.

`evaluate_cc_roll_chain()` (0173) can simulate hypothetical chains, but the Outcome Evaluator does not yet use it to reconstruct realized historical chains from `parent_cc_rec_id` lineage.

This directly limits Decision Quality for CC management actions. Even after the dashboard-context fix (0174) and lot-schedule improvements (0178), there won't be enough clean, fully-attributed outcomes to safely turn on DQ for roll actions.

## Proposed approach

In `outcome_evaluator.py`, when evaluating a ROLL recommendation at a horizon:

1. Walk the `parent_cc_rec_id` chain to find the next concrete outcome (BTC, ALLOW_ASSIGNMENT, or the terminal open rec).
2. If the terminal rec is closed (BTC or assignment), compute the realized return across the full chain: net premium collected across all legs minus the final BTC cost or assignment basis.
3. If the chain is still open (terminal rec has no close event), keep the existing "estimated" behavior.

Store the chain length as `roll_chain_depth INT` on `recommendation_outcomes` so the Decision Quality model can filter for fully-resolved chains (depth > 1) vs single-hop.

This is deferred until 0174 and 0178 are merged, since outcome math that reflects incorrect assignment decisions is not worth attributing.

## Touches

- `outcome_evaluator.py` — ROLL evaluation branch
- `agent_db.py` — `get_trade_chain()` helper (may already exist — verify and extend)
- `recommendation_outcomes` table — `roll_chain_depth INT` column migration
- `tests/test_lifecycle.py` — ROLL → ROLL → BTC chain produces single resolved outcome row

## Done when

- [ ] `recommendation_outcomes` has `roll_chain_depth` column
- [ ] ROLL evaluation at `at_expiry` horizon walks `parent_cc_rec_id` chain
- [ ] Fully-resolved ROLL chain produces non-null `actual_return`
- [ ] Still-open ROLL chain remains `actual_is_estimated=True`
- [ ] DQ model can filter on `roll_chain_depth IS NOT NULL AND actual_is_estimated = 0`
- [ ] Lifecycle test: 2-hop ROLL → BTC chain → single correct `actual_return`
