# Migrate Thesis DB to Full Pillar/Metrics/Rules Schema

- **ID:** 0030
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** high
- **Depends:** none

## Problem

The current `investment_theses` table stores only (ticker, version, summary, status). The `thesis_claims` table is a flat list with no importance weighting, no warning/violation bands, no qualitative signal support, and no add/trim/exit/CC rule storage. The agents in 0013 and the intake UI in 0020 both depend on a richer schema — but that schema has never been built. This item creates the full relational structure those agents require.

## Proposed approach

All changes in `agent_db.py` `migrate()`. Must be safe to run against the live optiplex DB (ALTER TABLE … ADD COLUMN; CREATE TABLE IF NOT EXISTS — no DROP).

**Extend `investment_theses`** (ALTER TABLE ADD COLUMN IF NOT EXISTS for each):
- `portfolio_role TEXT` — STRUCTURAL_BALLAST / CASH_FLOW / QUALITY_GROWTH / ASYMMETRIC / TACTICAL
- `thesis_summary TEXT` — plain-English rationale
- `holding_period TEXT` — `<1_YEAR` / `1_3_YEARS` / `3_5_YEARS` / `5_PLUS_YEARS` / `INDEFINITE`
- `conviction INTEGER` — 1 (exploratory) → 5 (highest)
- `target_weight_pct REAL`
- `max_weight_pct REAL`
- `approved_by TEXT` — e.g. `USER`
- `closed_reason TEXT`

Valid status values: DRAFT, ACTIVE, UNDER_REVIEW, BROKEN, CLOSED, SUPERSEDED

**Add `thesis_pillars`** (CREATE TABLE IF NOT EXISTS):
- `id INTEGER PRIMARY KEY`
- `thesis_id INTEGER NOT NULL REFERENCES investment_theses(id)`
- `name TEXT NOT NULL` — e.g. "Revenue Growth"
- `description TEXT`
- `importance REAL NOT NULL` — weights must sum to 100 across a thesis
- `critical INTEGER NOT NULL DEFAULT 0` — if 1, VIOLATED status triggers THESIS_CRITICAL_VIOLATION regardless of aggregate score
- `status TEXT NOT NULL DEFAULT 'UNKNOWN'` — STRONG / HEALTHY / WATCH / WARNING / VIOLATED / UNKNOWN
- `score REAL` — 0–100
- `confidence REAL` — 0–100
- `last_evaluated_at REAL`
- `reason TEXT` — prose explanation of current status

**Add `thesis_metrics`** (CREATE TABLE IF NOT EXISTS):
- `id INTEGER PRIMARY KEY`
- `pillar_id INTEGER NOT NULL REFERENCES thesis_pillars(id)`
- `metric_key TEXT NOT NULL` — maps to `company_financials` column
- `direction TEXT NOT NULL` — HIGHER_IS_BETTER / LOWER_IS_BETTER
- `healthy_rule_json TEXT` — `{"operator": ">=", "value": 15}`
- `warning_rule_json TEXT` — `{"operator": "BETWEEN", "min": 8, "max": 15}`
- `violation_rule_json TEXT` — `{"operator": "<", "value": 8}`
- `persistence_periods INTEGER NOT NULL DEFAULT 1` — consecutive periods required to confirm violation

**Add `thesis_rules`** (CREATE TABLE IF NOT EXISTS):
- `id INTEGER PRIMARY KEY`
- `thesis_id INTEGER NOT NULL REFERENCES investment_theses(id)`
- `rule_type TEXT NOT NULL` — ADD / TRIM / EXIT / RISK / COVERED_CALL / REVIEW_TRIGGER / QUALITATIVE_SIGNAL
- `rule_json TEXT NOT NULL` — the full rule body as JSON (structure varies by rule_type)

Keep `thesis_claims` as-is for backward compat. Add indexes on thesis_pillars(thesis_id), thesis_metrics(pillar_id), thesis_rules(thesis_id, rule_type).

**Update `agent_db.py` CRUD helpers** to add:
- `insert_thesis_pillar(thesis_id, name, …) → int`
- `insert_thesis_metric(pillar_id, metric_key, …) → int`
- `insert_thesis_rule(thesis_id, rule_type, rule_json) → int`
- `update_pillar_status(pillar_id, status, score, confidence, reason)`
- `get_thesis_pillars(thesis_id) → list[dict]`
- `get_thesis_metrics(pillar_id) → list[dict]`
- `get_thesis_rules(thesis_id, rule_type=None) → list[dict]`
- Extend `get_thesis()` to JOIN pillars and return composite thesis health score

## Touches

`agent_db.py` (migrate + CRUD helpers)

## Done when

- [ ] `migrate()` runs cleanly on the local dev DB and on the optiplex live DB without data loss
- [ ] `investment_theses` has all new columns (verified via `PRAGMA table_info`)
- [ ] `thesis_pillars`, `thesis_metrics`, `thesis_rules` tables exist with correct columns and FKs
- [ ] All new CRUD helpers exist and are importable without error
- [ ] `get_thesis()` returns pillar list and computed thesis health when pillars exist
- [ ] QA (backend): Run `migrate()` against the local dev DB and confirm via `PRAGMA table_info(investment_theses)` that all new columns exist. Confirm `thesis_pillars`, `thesis_metrics`, `thesis_rules` tables exist with correct columns. Import `agent_db` and call each new CRUD helper without error. Then run `migrate()` again to confirm idempotency (no crash on second run). Show PRAGMA output before checking this box.
