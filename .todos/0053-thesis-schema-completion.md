# Complete Thesis Schema (Qualitative Signals, Risks/Catalysts, Valuation Framework)

- **ID:** 0053
- **Status:** done
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

## Outcome

- **`thesis_engine.py`**: `draft_thesis()` now returns `qualitative_signals` (list of dicts with description/source/direction) and `review_triggers` (list of plain strings). `key_risks` and `catalysts` are now normalized to structured dicts with severity/importance and time_horizon. Both string and dict formats handled gracefully.
- **`agent_db.py`**: Added `thesis_risks` and `thesis_catalysts` CREATE TABLE blocks (previous session). Added `insert_thesis_risk()` and `insert_thesis_catalyst()` helpers. `get_thesis_full()` now includes `db_risks` and `db_catalysts` from the new tables. `review_triggers` migration column on `investment_theses` added (previous session).
- **`serve.py`**: `_handle_thesis_approve()` now persists risks (with severity/time_horizon), catalysts (with importance/time_horizon), qualitative signals (as QUALITATIVE_SIGNAL rules to `thesis_rules`), and review_triggers JSON to `investment_theses`. The Thesis Monitor's existing QUALITATIVE_SIGNAL handler now gets populated data.
- **`generate_dashboard.py`** / `out/dashboard.html`: Draft review renders both string and dict risks/catalysts with severity/importance color badges. Active thesis view now shows `db_risks` and `db_catalysts` as structured lists (passed from `thesis.db_risks`/`db_catalysts`). Valuation framework not added (no per-thesis valuation data model exists yet; would be a future item).

## Done when

- [x] `thesis_engine.py` generates QUALITATIVE_SIGNAL rules in its output
- [x] Thesis Monitor processes QUALITATIVE_SIGNAL rules without error (existing handling in thesis_agent.py reads from thesis_rules, now populated on approval)
- [x] `thesis_risks` and `thesis_catalysts` tables exist and are populated for each thesis
- [x] `investment_theses` has a `review_triggers` field
- [x] Thesis intake UI shows risks and catalysts as structured lists (severity/importance badges in draft review; db_risks/db_catalysts in active view)
- [x] **Backend QA:** deployed to optiplex — service active, generate_dashboard regenerated
- [x] **Frontend QA:** dashboard regenerated without errors; service active
- [x] **No service regression:** `systemctl is-active investment` → active
