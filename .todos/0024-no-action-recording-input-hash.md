# Add NO_ACTION Recording with Input Hash Deduplication

- **ID:** 0024
- **Status:** backlog
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

## Touches

`agent_db.py` (input hash logic, upsert-or-skip), `agents/orchestrator.py` (pass hash to each agent), `recommendations` table (add `input_hash`, `updated_at` columns — migration), `serve.py` (`GET /api/agents/coverage`), `generate_dashboard.py` (expandable NO_ACTION footer)

## Done when

- [ ] Every HOLD/NO_ACTION result is recorded (not silently discarded)
- [ ] Identical-state evaluations within 24h update timestamp only — no duplicate rows
- [ ] `input_hash` stored on every recommendation row
- [ ] Material change (price, thesis, macro, earnings) causes new row even within 24h
- [ ] `GET /api/agents/coverage` returns per-ticker, per-agent-type coverage status
- [ ] Decision Queue footer shows count of NO_ACTION evaluations from latest run
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced

