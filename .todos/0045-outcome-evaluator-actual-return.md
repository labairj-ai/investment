# Fix Outcome Evaluator: actual_r Must Reflect User's Actual Decision

- **ID:** 0045
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

In `outcome_evaluator.py`, `actual_r` is set to `hold_r` (the stock's return from recommendation date to horizon). This means "actual" always equals "what the stock did" regardless of what the user actually chose to do. For a rejected EXIT recommendation, this is correct. For an accepted TRIM, accepted BUY, or accepted EXIT, it is wrong — the actual return should reflect the fraction sold/bought and any cash redeployment. The claimed `UserOverrideAlpha = actual - agent` is therefore not yet valid: it measures holding-return vs agent-return, not decision-return vs agent-return.

## Proposed approach

- Add an `executed_actions` table (or link to existing decision/transaction records) that records what actually happened: accepted/rejected, quantity, execution price, redeployment ticker (if any).
- Update `_compute_scenarios()` to branch on the decision outcome:
  - Accepted EXIT: `actual_r` = cash or redeployment return after execution price
  - Rejected EXIT: `actual_r` = hold return (current behavior, correct)
  - Accepted TRIM: `actual_r` = (trimmed_fraction × redeployment_r) + (remaining_fraction × hold_r)
  - Accepted BUY: `actual_r` = incremental shares × subsequent stock return from execution
- If no executed-action record exists for a recommendation, fall back to `hold_r` and flag `actual_is_estimated=True`.
- Open question: where do execution prices come from? Manual entry in Decision Queue UI, or inferred from cost_lots changes?

## Touches

- `agents/outcome_evaluator.py` (`_compute_scenarios`)
- `agent_db.py` (new `executed_actions` table or linkage)
- `serve.py` (Decision Queue accept endpoint — record execution details)

## Done when

- [ ] Accepted EXIT recommendations compute `actual_r` from execution price / redeployment, not hold_r
- [ ] `UserOverrideAlpha` for a rejected recommendation still equals `actual_r - agent_r` (hold_r - agent_r)
- [ ] `actual_is_estimated` flag present in outcome rows where no execution record exists
- [ ] At least one end-to-end test: accept a mock EXIT, verify `actual_r ≠ hold_r` in outcome row
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change
