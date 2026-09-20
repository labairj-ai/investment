# Add Immutable Run Ledger and Quality Tracking to Macro Scoring

- **ID:** 0470
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0463

## Problem

Each Saturday macro scoring run produces scores that are written directly to `holding_macro_scores` with no accompanying run record. There is no way to audit whether a given week's scores are complete, which model or prompt version generated them, whether the macro data snapshot was stale, or how many tickers failed silently. This is the same observability gap that motivated the Learning Lab sweep ledger — without a run record, operational failures are invisible and the historical score table cannot be trusted as a complete dataset.

## Proposed approach

- Create a `macro_scoring_runs` table with columns: `run_id` (UUID), `run_at`, `expected_tickers`, `scored_tickers`, `failed_tickers`, `model_version`, `prompt_version`, `macro_snapshot_hash`, `source_completeness_json` (per-indicator: series_id, observation_date, stale), `coverage_pct`, `status` (`COMPLETE` / `PARTIAL` / `FAILED`)
- Write the ledger row at the start of each run (status=`IN_PROGRESS`), update it on completion
- Link each `holding_macro_scores` row back to its `run_id` via a foreign key
- Surface run quality in the dashboard: coverage %, stale indicators, last successful run date
- Treat a run with coverage below a threshold (e.g. <80%) as `PARTIAL` and flag it in the dashboard rather than displaying the scores as if complete
- Immutability: never update or delete ledger rows; append-only

## Touches

- Macro scoring runner (`portfolio_ai.py` or equivalent Saturday job)
- New `macro_scoring_runs` table migration
- `holding_macro_scores` table (add `run_id` FK column)
- Dashboard macro risk tab (surface run quality)

## Done when

- [ ] Every Saturday scoring run writes a `macro_scoring_runs` ledger row before and after execution
- [ ] Each `holding_macro_scores` row carries a `run_id` linking it to its run record
- [ ] A run with any silent failures is marked `PARTIAL`, not `COMPLETE`
- [ ] Dashboard shows last run's coverage %, model version, and any stale indicators
