# Make Macro Scoring Ledger Fail-Closed and Exact

- **ID:** 0478
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0470, 0475

## Problem

`macro_scoring_runs` exists but behaves fail-open in several ways: the initial `INSERT` (STARTED row) is wrapped in a try/except that silently swallows failures, so a run can proceed without a ledger record; the final `UPDATE` failure is also swallowed, leaving the row permanently IN_PROGRESS; `COMPLETE` is set when `failed_n == 0` rather than when `scored_n == expected_n`, so a run that produces no results at all can appear complete; a valid JSON response containing unexpected or missing tickers causes neither `scored_n` nor `failed_n` to increment; the `run_id` is only 8 UUID characters; and `macro_hash` is computed only over scalar top-level context fields, excluding the nested regime object and provenance measurements that represent the actual scoring inputs.

## Proposed approach

Mirror the Learning Lab `learning_sweep_runs` fail-closed pattern:
- **STARTED row is mandatory**: write `status='STARTED'` before the first LLM call; if the INSERT fails, raise immediately — do not continue the run without a ledger record.
- **Exact count semantics**: `COMPLETE` only when `scored_n == expected_n`; `PARTIAL` when `scored_n > 0` but `< expected_n`; `FAILED` when `scored_n == 0`. Count each expected ticker exactly once in either `scored_n` or `failed_n` — a response that omits a ticker counts as a failure for that ticker.
- **Full UUID**: use `str(uuid.uuid4())` for `run_id` (no truncation).
- **Canonical input hash**: compute SHA-256 over a deterministic JSON serialisation of the full macro context (including `measurements` and `regime` sub-dicts, sorted keys, no floats that vary by retrieval time). Store the first 16 hex chars.
- **Durable errors**: add an `errors_json` TEXT column to `macro_scoring_runs`; accumulate per-ticker error messages and write them on completion.
- **Final UPDATE is non-optional**: if the closing UPDATE fails, log loudly and re-attempt once; do not silently drop.

## Touches

- `portfolio_ai.py` — `_init_ai_tables()` (add `errors_json` column), `generate_holding_macro_scores()` (ledger lifecycle)
- `macro_scoring_runs` schema

## Done when

- [x] A run that cannot write the STARTED row raises rather than continuing
- [x] `COMPLETE` only when `scored_n == expected_n`; every expected ticker is accounted for in either counter
- [x] `run_id` is a full UUID (36 chars)
- [x] `macro_hash` covers the nested `measurements` and `regime` objects, not just scalar top-level fields
- [x] `errors_json` column stores per-ticker failure messages
- [x] Final UPDATE failure is logged and retried, never silently dropped
