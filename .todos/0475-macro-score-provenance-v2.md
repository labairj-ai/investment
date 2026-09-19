# Add Full Provenance Columns to Macro Score History Table

- **ID:** 0475
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0470

## Problem

`holding_macro_scores_history` stores only `ticker`, `scores` (JSON blob), and `scored_at` timestamp. A historical score cannot be traced to the run that produced it, the model that generated it, the prompt version used, or the evidence that was fed in. This makes it impossible to distinguish score drift caused by a model upgrade from genuine company-level changes, and means the history table cannot serve as an auditable record. The Learning Lab's `learning_sweep_runs` table already holds this level of provenance — macro scoring should match the same standard.

## Proposed approach

- Add columns to `holding_macro_scores_history` via `ALTER TABLE ... ADD COLUMN` (with `try/except` for idempotency):
  - `run_id TEXT` — full UUID from `macro_scoring_runs` (not the current 8-char truncation)
  - `model_version TEXT` — model identifier used for this score
  - `prompt_hash TEXT` — SHA-256 (first 12 chars) of the exact prompt string sent to the model
  - `schema_version TEXT` — `MACRO_SCORE_SCHEMA_VERSION` constant value
  - `evidence_hash TEXT` — SHA-256 (first 12 chars) of the evidence dict passed to the prompt for this ticker
- Populate these columns on every `INSERT INTO holding_macro_scores_history` in `generate_holding_macro_scores()`.
- Upgrade `macro_scoring_runs.run_id` from 8-char truncated UUID to full UUID (new runs only; old rows keep truncated IDs).
- Expose `run_id`, `model_version`, `schema_version` in the dashboard macro run-quality display so a user can see which model produced the currently displayed scores.

## Touches

- `portfolio_ai.py` — `_init_ai_tables()` (schema migration), `generate_holding_macro_scores()` (INSERT with new columns), run_id generation
- Dashboard macro run quality card

## Done when

- [x] Every new `holding_macro_scores_history` row carries `run_id`, `model_version`, `prompt_hash`, `schema_version`, `evidence_hash`
- [x] `run_id` in `macro_scoring_runs` is a full UUID (not 8-char)
- [x] Given a historical score row, it is possible to identify exactly which run, model, prompt, and evidence produced it
- [x] Dashboard macro quality card surfaces model version and run ID for the most recent scoring run
