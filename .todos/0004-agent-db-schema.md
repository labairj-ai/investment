# Create Agent Infrastructure DB Schema

- **ID:** 0004
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** high
- **Depends:** none

## Problem

The current `_jobs` system lives in memory and completed jobs expire after 10 minutes. There is no persistent record of why an analysis ran, what data it saw, what it concluded, what the critic said, what the user decided, or whether the recommendation turned out to be right. Without persistent history, agents cannot be audited, improved, or measured. This schema is the foundation every subsequent agent phase depends on.

## Proposed approach

Add the following tables to `investment.db` via a migration script (`agent_db_migrate.py` or added to the existing schema init):

- `agent_runs` — one row per agent invocation: agent_type, scope, ticker, trigger_type, trigger_key, status, model, prompt_version, input_hash, input_snapshot_json, started_at, finished_at, error
- `agent_findings` — one row per finding from a run: run_id FK, ticker, finding_type, severity (0–100), confidence (0–100), summary, why_now, metrics_json, evidence_json, created_at, expires_at
- `recommendations` — actionable outputs: run_id FK, ticker, action, action_payload_json, recommendation_score, confidence, priority, why_now, rationale, counter_case, no_action_case, status (open/accepted/rejected/deferred/expired/superseded), valid_until, created_at
- `critic_reviews` — one row per recommendation review: recommendation_id FK, verdict (APPROVE/APPROVE_WITH_CAUTION/CHALLENGE/VETO), strongest_objection, missing_evidence_json, confidence_adjustment, created_at
- `investment_theses` — per-ticker thesis: ticker, version, summary, status, created_at, approved_at, closed_at
- `thesis_claims` — per-claim within a thesis: thesis_id FK, claim text, claim_type, metric_key, operator, threshold, persistence_periods, weight, current_status, last_evaluated_at
- `user_decisions` — audit trail: recommendation_id FK, decision, reason_code, notes, decided_at. Reason codes: AGREE, DISAGREE_THESIS, TAX, UPSIDE_PREFERENCE, LIQUIDITY, RISK_LIMIT, WAIT_FOR_EVENT, OTHER
- `recommendation_outcomes` — for the outcome evaluator: recommendation_id FK, evaluation_date, benchmark_return, actual_return, recommended_path_return, opportunity_cost, notes

All tables use INTEGER PRIMARY KEY with created_at REAL (Unix timestamp).

## Touches

`investment.db` (schema), new `agent_db.py` (migration + helpers), `serve.py` (init call at startup)

## Done when

- [ ] Migration script creates all 8 tables idempotently (safe to re-run)
- [ ] `agent_db.py` has helper functions for insert/query on each table
- [ ] `serve.py` calls migration at startup so the optiplex DB is updated on next pull + restart
- [ ] Manual inspection of `investment.db` shows all tables present with correct columns
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced

