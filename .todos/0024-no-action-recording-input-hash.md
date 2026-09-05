# Add NO_ACTION Recording with Input Hash Deduplication

- **ID:** 0024
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0004, 0005

## Problem

Without recording NO_ACTION evaluations, the decision history is heavily biased toward the decisions that were made, making it impossible to measure what happened to positions where the system deliberately concluded nothing should change. The outcome evaluator (0018) and preference learner (0027) both need full evaluation coverage to produce valid statistics. But naively recording a NO_ACTION every time the trigger engine runs against an unchanged position would flood the database with meaningless duplicate rows.

## Proposed approach

**NO_ACTION as a first-class recommendation status:**
Every agent evaluation that concludes HOLD or NO_ACTION should be recorded — but only once per meaningfully distinct state.

**Input hash deduplication:**
For each evaluation, compute a deterministic hash of:
- Ticker
- Recommendation type (the agent type)
- Relevant data state: latest price (rounded to nearest 0.5%), current thesis version, macro score for this ticker, most recent financial statement quarter

`input_hash = sha256(ticker + agent_type + price_bucket + thesis_version + macro_score + latest_quarter)`

Before writing a NO_ACTION:
1. Query `recommendations` for the same ticker + agent_type with status `no_action` and identical `input_hash`
2. If found and within configurable staleness window (default: 24h): update `updated_at` timestamp only, no new row
3. If not found or outside staleness window: write new NO_ACTION row

**Evaluation coverage metrics (new `GET /api/agents/coverage` endpoint):**
Returns for each ticker:
- Last evaluation timestamp per agent type
- Last recommendation type (HOLD / REVIEW / TRIM etc.)
- Days since last full evaluation
- Coverage gap flag if any agent hasn't evaluated in > N days

**Dashboard "No action" footer:**
The Decision Queue footer shows: "No action: N positions reviewed since [last run]"
Clicking it expands a table of all HOLD/NO_ACTION findings from the latest orchestrator run.

**What counts as a material change (resets the hash, forces new record):**
- Price moved > 2% since last evaluation
- Thesis version changed
- Macro score changed ≥ 1 point
- New earnings quarter available

## Outcome

- `agent_db.py`: Added `input_hash` + `updated_at` columns (migration), `compute_input_hash()` (log-scale ~2% price buckets via `round(log(price)/log(1.02))`), `upsert_no_action()` (24h dedup — UPDATE timestamp if hash matches, INSERT otherwise), `get_coverage()` endpoint data.
- `agents/orchestrator.py`: `_record_no_actions()` auto-generates NO_ACTION rows for all holdings not flagged by a holding-scope agent after each run. Holding-scope set: `portfolio_guardian`, `thesis_monitor`, `covered_call`.
- `serve.py`: `GET /api/agents/coverage` route; `_run_thesis_monitor_weekly()` thread (Saturday 7am ET).
- `generate_dashboard.py`: `loadDecisionQueue()` fetches coverage data; footer `#dq-no-action` shows real DB count.
- Browser QA (2026-09-05): zero JS errors; footer showed "27 positions reviewed in last 24h"; second portfolio_guardian run confirmed 27 rows (same count), timestamps bumped — dedup working.
- Note for 0027 (preference learner): NO_ACTION rows are now in `recommendations` table with `status='no_action'` and can be joined via `agent_runs` for agent_type.

## Touches

`agent_db.py` (input hash logic, upsert-or-skip), `agents/orchestrator.py` (pass hash to each agent), `recommendations` table (add `input_hash`, `updated_at` columns — migration), `serve.py` (`GET /api/agents/coverage`), `generate_dashboard.py` (expandable NO_ACTION footer)

## Done when

- [x] Every HOLD/NO_ACTION result is recorded (not silently discarded)
- [x] Identical-state evaluations within 24h update timestamp only — no duplicate rows
- [x] `input_hash` stored on every recommendation row
- [x] Material change (price, thesis, macro, earnings) causes new row even within 24h
- [x] `GET /api/agents/coverage` returns per-ticker, per-agent-type coverage status
- [x] Decision Queue footer shows count of NO_ACTION evaluations from latest run
- [x] Browser QA (mandatory — do not skip): Run agents, then open the dashboard in a browser and verify: (a) zero JS console errors, (b) Decision Queue footer shows 'N positions reviewed' count matching NO_ACTION rows in DB, (c) running agents again with identical state within 24h updates timestamp only — no duplicate rows (check DB directly). Do NOT check this box without completing live browser testing.

