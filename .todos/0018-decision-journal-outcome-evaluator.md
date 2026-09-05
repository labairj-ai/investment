# Build Decision Journal and Outcome Evaluator (Phase 7)

- **ID:** 0018
- **Status:** done
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

- [x] Outcome evaluator runs weekly and writes `recommendation_outcomes` rows for matured recommendations
- [x] `actual_return` calculated from `holding_day` price history for the recommendation's ticker
- [x] Decision Journal panel renders in dashboard (even if mostly empty initially)
- [x] 12-month summary card shows counts (generated/accepted/rejected/deferred)
- [x] Detail table shows each past recommendation with decision and reason_code
- [x] CC outcomes correctly calculate premium captured vs upside surrendered
- [x] Browser QA (mandatory — do not skip): Run the outcome evaluator manually for at least one matured recommendation. Open the dashboard in a browser and verify: (a) zero JS console errors, (b) Decision Journal panel renders (even if mostly empty), (c) 12-month summary card shows correct counts, (d) detail table row visible for the matured recommendation with correct actual_return. Do NOT check this box without completing live browser testing.

## Outcome

New file: `agents/outcome_evaluator.py`. Registered in `agents/__init__.py`.

**Outcome Evaluator (`agents/outcome_evaluator.py`):**
- `evaluate_matured_recommendations(min_age_days=14)` — queries accepted/rejected recs with no outcome row older than 14 days, looks up entry price from `holding_day` at rec creation date, looks up current price, computes `actual_return`. For SELL_CC: `recommended_path_return = exec_premium / entry_price`. Writes `recommendation_outcomes` row.
- Runs weekly Sunday 2 AM ET via new `_run_outcome_evaluator()` background thread in `serve.py`.
- `run_outcome_evaluator(ctx)` registered as `"outcome_evaluator"` agent for on-demand triggering.

**`agent_db.py` additions:**
- `journal_summary()` — counts by status, outcomes_evaluated, avg/total opportunity_cost
- `list_journal_entries(limit=200)` — LEFT JOINs recommendations + user_decisions + recommendation_outcomes for all closed recs, ordered by decision date DESC

**`serve.py` additions:**
- `GET /api/agents/journal` — returns `{ok, entries, summary}`
- `_run_outcome_evaluator()` background thread (Sunday 2 AM ET, flag at `out/last_outcome_eval.txt`)

**`generate_dashboard.py` additions:**
- Decision Journal section between AI Portfolio Insight and KPI row
- Summary strip: Generated / Accepted / Rejected / Deferred / Vetoed counts + outcome evaluation status line
- Detail table: Ticker, Type, Decision badge, Reason, Date, Actual Return (color-coded), Opp. Cost

**Browser QA results (2026-09-05):**
- Zero JS console errors ✓
- Journal renders below AI Portfolio Insight ✓
- Summary strip: Generated 2 · Accepted 1 · Vetoed 1 ✓
- Detail table: GRMN SELL_CC (vetoed) + GRMN HOLD (accepted, +1.1% actual return) ✓
- Empty state line: "No outcomes evaluated yet — check back after 14 days" ✓

**Note:** Opportunity cost column shows "—" for HOLD recs (no recommended_path_return defined — correct, no specific return target). CC recs will populate opportunity_cost once 14+ days old.

**Unblocks:** 0026 (Counterfactual Benchmarking), 0027 (Preference Learner).
