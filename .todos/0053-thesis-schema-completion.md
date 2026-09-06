# Complete Thesis Schema (Qualitative Signals, Risks/Catalysts, Valuation Framework)

- **ID:** 0053
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

The thesis engine (0030–0033) generates pillars, weights, thresholds, and persistence rules. But several pieces designed in the full thesis framework are missing or incomplete: (1) `thesis_engine.py` does not generate `QUALITATIVE_SIGNAL` rules, even though the Thesis Monitor has code to process them. (2) Key risks and catalysts are returned by the AI generator but not stored as structured DB entities — they exist only as JSON blobs. (3) No per-thesis valuation framework is stored. (4) No per-thesis review-trigger policy (what events should trigger a full thesis re-evaluation). (5) CC policy (covered in 0052 as its own item).

## Proposed approach

- **Qualitative signals**: add generation of `QUALITATIVE_SIGNAL` rules in `thesis_engine.py`; each should have a signal description, source (news/management/channel), direction (positive/negative), and weight. Store in `thesis_rules` or `thesis_pillars`.
- **Risks/Catalysts**: add `thesis_risks` and `thesis_catalysts` tables with structured fields (description, severity/importance, time_horizon, monitoring_frequency). Populate from AI generator output.
- **Valuation framework**: add a `thesis_valuation_framework` field (or table) with preferred metrics, historical percentile references, and fair-value estimate.
- **Review-trigger policy**: add `review_triggers` JSON to `investment_theses` — list of conditions (e.g. "revenue miss >10%", "management change") that should fire a full thesis re-evaluation.
- Update `thesis_engine.py` and the thesis AI proposal engine to generate all of the above.

## Touches

- `thesis_engine.py`
- `agents/thesis_agent.py` (process QUALITATIVE_SIGNAL rules)
- DB schema migrations (new tables/columns)
- `serve.py` / thesis intake UI (display/edit new fields)

## Done when

- [ ] `thesis_engine.py` generates QUALITATIVE_SIGNAL rules in its output
- [ ] Thesis Monitor processes QUALITATIVE_SIGNAL rules without error
- [ ] `thesis_risks` and `thesis_catalysts` tables exist and are populated for each thesis
- [ ] `investment_theses` has a `review_triggers` field
- [ ] Thesis intake UI shows risks and catalysts as structured lists (not raw JSON)
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change
