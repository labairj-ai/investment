# Refactor Thesis Intake UI for Full Pillar/Rules Schema

- **ID:** 0032
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0020, 0030, 0031

## Problem

The thesis intake form and approval flow in 0020 were designed around the old flat `thesis_claims` model. Now that 0030 defines a richer relational schema (pillars, metrics, rules) and 0031 provides an AI proposal engine that returns that structure, the existing endpoints and dashboard UI need to be updated to match. Without this, the intake form can collect user input but has no way to persist it correctly or show the AI's proposed pillar details for review.

## Proposed approach

**API changes (serve.py):**
- `POST /api/theses/{ticker}/draft` — call `thesis_engine.draft_thesis(ticker, intake_dict)`; return full pillar/metrics/rules JSON to the frontend (no DB write yet)
- `POST /api/theses/{ticker}/approve` — write `investment_theses` (with portfolio_role, holding_period, conviction, target_weight_pct, max_weight_pct), then `thesis_pillars`, `thesis_metrics`, and `thesis_rules` rows from 0030 schema. Always create a new version (N+1) and set the previous active version to SUPERSEDED — never overwrite
- `GET /api/theses/{ticker}/history` — return all versions with status and approved_at

**Intake form additions (generate_dashboard.py):**
- `portfolio_role` dropdown: STRUCTURAL_BALLAST / CASH_FLOW / QUALITY_GROWTH / ASYMMETRIC / TACTICAL
- `holding_period` dropdown: <1_YEAR / 1_3_YEARS / 3_5_YEARS / 5_PLUS_YEARS / INDEFINITE
- `conviction` slider 1–5
- `target_weight_pct` and `max_weight_pct` number inputs

**Draft review UI:**
- Show each proposed pillar as a card: name, importance %, description
- Within each card: metric table (metric_key / healthy / warning / violation / persistence) and qualitative signals list
- Per-pillar [Approve] / [Edit] controls; edited pillars re-validate importance sum
- "Critical pillar" checkbox per pillar — if checked, a VIOLATED status on that pillar alone triggers THESIS_CRITICAL_VIOLATION regardless of aggregate score
- Separate collapsible sections for: Valuation Framework, Covered Call Policy, Exit Rules, Trim Rules, Add Rules, Review Triggers, Key Risks, Catalysts

**Versioning rule:** approve always increments version; previous ACTIVE row → SUPERSEDED. History tab on the thesis page shows all versions.

## Touches

`serve.py` (endpoint updates), `generate_dashboard.py` (intake form + draft review UI), `thesis_engine.py` (called from updated draft endpoint), `agent_db.py` (CRUD helpers from 0030 used by approve endpoint)

## Outcome

Full end-to-end flow working on production optiplex. Two bugs found and fixed during browser QA:

1. **`get_thesis_full` ordering** (`agent_db.py`): `ORDER BY version DESC` was non-deterministic when DRAFT and ACTIVE rows share version=1. Fixed to `ORDER BY CASE WHEN status='DRAFT' THEN 1 ELSE 0 END DESC, id DESC` so a pending draft is always returned first.

2. **`approve_thesis` versioning** (`agent_db.py`): `new_version = MAX(version)` didn't increment because MAX counted the draft row itself. Fixed to snapshot the current ACTIVE version before superseding it, then `new_version = prior_max + 1`. First approval gives v1, second gives v2, etc.

QA confirmed with GRMN:
- Intake form pre-fills from existing intake_json; dropdown option values use canonical codes (QUALITY_GROWTH etc.) with user-friendly labels
- Draft review UI shows pillar cards with importance badge, Critical checkbox, metric table (healthy/warning/violation/persist), rules (ADD/TRIM/EXIT), key risks, catalysts; Approve button
- Critical=1 persisted correctly for the checked pillar
- DB writes: 4 tables (investment_theses id=31 v2 ACTIVE; thesis_pillars ×4; thesis_metrics ×4; thesis_rules ×3)
- History endpoint: returns ACTIVE v2 + 2× SUPERSEDED v1 rows in correct order
- Zero JS console errors throughout

## Done when

- [x] Intake form includes portfolio_role, holding_period, conviction, target/max weight fields
- [x] Draft endpoint calls `thesis_engine.draft_thesis()` and returns full pillar structure
- [x] Draft review UI renders each pillar card with metrics and qualitative signals
- [x] Critical pillar checkbox is present and stored in `thesis_pillars.critical`
- [x] Approve endpoint writes all four tables (investment_theses, thesis_pillars, thesis_metrics, thesis_rules) correctly
- [x] Approving a second time creates version 2 and marks version 1 SUPERSEDED
- [x] `GET /api/theses/{ticker}/history` returns all versions
- [x] Browser QA (mandatory — do not skip): Open the dashboard in a browser, click a Thesis button for a held ticker, and exercise the full intake → draft → approve flow: (a) zero JS console errors, (b) intake form shows all new fields (portfolio_role, holding_period, conviction, target/max weight), (c) draft renders each pillar card with metrics, (d) critical pillar checkbox visible and saves to DB, (e) approve writes all four tables (verify via `PRAGMA table_info` or DB query), (f) approving a second time creates version 2 and marks version 1 SUPERSEDED. Do NOT check this box without completing live browser testing.
