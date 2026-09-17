# Use Live AgentContext Snapshot for Overweight Gate, Not Stale holding_day

- **ID:** 0160
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

The `only_if_overweight` gate in `_check_assignment_eligible()` reads portfolio weight from the last `portfolio_day` / `holding_day` DB rows, which are written once per day by the newsletter. If ANET moves 12% intraday, its stored weight may be materially wrong at option-management time — the gate can approve or block assignment based on yesterday's stale portfolio weight.

`AgentContext.snapshot` (available in `_analyze_roll()`) already holds a `PortfolioSnapshot` with `holdings[*].weight_pct` computed fresh from current prices at agent-run time. That is the correct data source for a live management decision.

## Proposed approach

Pass the live weight directly rather than having `_check_assignment_eligible()` query the DB:

1. In `_analyze_roll()` (or wherever `evaluate_cc_management_state()` is called), look up `ticker` in `ctx.snapshot.holdings` to extract `weight_pct`.
2. Pass `current_weight_pct` as a parameter to `evaluate_cc_management_state()` and thread it into `_check_assignment_eligible()`.
3. Replace the DB `portfolio_day` / `holding_day` query in Gate 5 with a direct comparison of the passed-in `current_weight_pct` vs `thesis.max_position_pct`.

This is a prerequisite for the broader `ManagementPolicyContext` refactor (0162) but can be done independently now.

## Touches

- `agents/covered_call_agent.py` — `_analyze_roll()`: extract `weight_pct` from `ctx.snapshot.holdings`; pass to `evaluate_cc_management_state()`
- `covered_call_rec.py` — `evaluate_cc_management_state()` signature: add `current_weight_pct: float | None = None`; `_check_assignment_eligible()` signature: add same; replace DB query with passed-in value
- `tests/test_covered_call_agent.py` — test that overweight gate uses provided weight, not DB

## Done when

- [ ] `only_if_overweight` gate compares `current_weight_pct` (from snapshot) vs `max_position_pct`
- [ ] No `portfolio_day` / `holding_day` query inside `_check_assignment_eligible()` for the overweight path
- [ ] Falls back gracefully (skip gate) when `current_weight_pct` is None
- [ ] Existing tests pass
