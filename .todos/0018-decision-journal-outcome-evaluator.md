# Build Decision Journal and Outcome Evaluator (Phase 7)

- **ID:** 0018
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** low
- **Depends:** 0016, 0004

## Problem

Without measuring outcomes, the system can never determine where it adds value and where the user's overrides are superior. The `user_decisions` and `recommendation_outcomes` tables (from 0004) will accumulate data over time, but there is no UI or analysis layer that makes that data meaningful. The Outcome Evaluator is what eventually answers: "Where is the AI better than me, and where am I better than the AI — and under what conditions?"

## Proposed approach

Two components:

**1. Outcome Evaluator (backend, scheduled)**

A periodic job (runs weekly or monthly) that evaluates recommendations that have matured:
- For each closed recommendation (accepted or rejected) older than N days: fetch actual price change from `holding_day` history.
- Calculate: `recommended_path_return` (what would have happened if the recommendation was followed) vs `actual_return` (what actually happened).
- For CC: compare premium captured vs upside surrendered if assigned.
- Write results to `recommendation_outcomes` table.
- `opportunity_cost` = `actual_return - recommended_path_return` (positive means user override outperformed).

**2. Decision Journal UI (dashboard section)**

A "Decision History" panel in the dashboard showing:

Rolling 12-month summary card:
- Recommendations generated / accepted / rejected / deferred
- Agent-followed return vs user-override return
- Net opportunity cost/benefit of overrides
- Best override pattern (e.g., "Avoiding premature CC" — derived from reason_codes)
- Worst override pattern
- Agent false positive rate (flagged → no material outcome)
- Agent false negative rate (not flagged → material event occurred)

Detail table: each past recommendation with decision, reason_code, recommended action, actual outcome, opportunity cost.

Filter by: agent type, ticker, date range, decision type.

This panel is informational only — it does not generate new recommendations.

**Data requirements**: meaningful data only starts accumulating after 0016 (Decision Queue) is live and being used. The evaluator can run but will produce sparse results initially. Build it now so the journal starts filling as soon as decisions are made.

## Touches

`agent_db.py` (outcome writer), `recommendation_outcomes` table (from 0004), `serve.py` (new `GET /api/agents/outcomes` endpoint), `generate_dashboard.py` (Decision Journal section), new scheduled job in `serve.py` scheduler

## Done when

- [ ] Outcome evaluator runs weekly and writes `recommendation_outcomes` rows for matured recommendations
- [ ] `actual_return` calculated from `holding_day` price history for the recommendation's ticker
- [ ] Decision Journal panel renders in dashboard (even if mostly empty initially)
- [ ] 12-month summary card shows counts (generated/accepted/rejected/deferred)
- [ ] Detail table shows each past recommendation with decision and reason_code
- [ ] CC outcomes correctly calculate premium captured vs upside surrendered
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced

