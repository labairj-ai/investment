# Active Model Registry Fix

- **ID:** 0344
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0342

## Problem

`ChallengerModel.load_latest()` loads the newest model by `created_at`, regardless of lifecycle state. The caller (`get_model()` / `apply_challenger_adjustment()`) then checks `lifecycle_state == PAPER_ACTIVE` and returns `None` if it isn't. This means training a new challenger model (lifecycle=TRAINED) silently deactivates the incumbent PAPER_ACTIVE model: `load_latest()` returns `edge_v2` (TRAINED), the lifecycle check fails, and the real PAPER_ACTIVE `edge_v1` is never loaded. The active challenger stops adjusting scores with no error or log message.

Additionally, nothing prevents two models from holding `lifecycle_state = 'PAPER_ACTIVE'` simultaneously, and `save_with_weights()` currently appears to use INSERT OR REPLACE semantics that could overwrite existing model data.

## Proposed approach

- Add `ChallengerModel.load_paper_active()` classmethod: queries `learning_models WHERE lifecycle_state = 'PAPER_ACTIVE' ORDER BY created_at DESC LIMIT 1` — completely independent of the latest-trained model
- Replace all callsites of `load_latest()` that are trying to get the scoring model with `load_paper_active()`; keep `load_latest()` for training/admin use only and rename it `load_latest_trained()` to make the distinction explicit
- Add a DB-level uniqueness constraint (or a `migrate()`-time check/trigger) enforcing at most one `PAPER_ACTIVE` model; when `promote()` transitions a model to `PAPER_ACTIVE`, automatically retire any existing `PAPER_ACTIVE` model first (with a log row)
- Ensure `save_with_weights()` uses `INSERT` (not replace) so existing model rows are immutable after creation; updates to lifecycle state go through `promote()` only
- Add test: seed PAPER_ACTIVE edge_v1, train edge_v2 (TRAINED), assert `load_paper_active()` still returns edge_v1 and scoring still applies

## Touches

- `agents/learning/calibration.py` — `load_latest()` → `load_latest_trained()`; new `load_paper_active()`; `promote()` retires existing PAPER_ACTIVE before activating a new one; `save_with_weights()` INSERT not replace
- `agents/learning/challenger.py` — callsite update from `load_latest()` to `load_paper_active()`
- `agent_db.py` — optional UNIQUE partial index on `(lifecycle_state)` WHERE `lifecycle_state='PAPER_ACTIVE'`
- `tests/test_calibration.py` — add regression test for the "train new model deactivates incumbent" scenario

## Done when

- [x] `load_paper_active()` exists and returns the PAPER_ACTIVE model regardless of whether a newer TRAINED model exists
- [x] Training a new challenger model does not deactivate or shadow the currently PAPER_ACTIVE one
- [x] At most one model can hold `PAPER_ACTIVE` at any time; promoting a second auto-retires the first with a log entry
- [x] `save_with_weights()` is immutable — model rows cannot be silently overwritten
- [x] `python -m pytest tests/` passes with no regressions

## Outcome

`load_paper_active()` added to `ChallengerModel`, queries by `lifecycle_state='PAPER_ACTIVE'` only. `challenger.py` `get_model()` now calls it directly. `_write()` changed from INSERT OR REPLACE to INSERT (raises IntegrityError on duplicate). `promote()` auto-retires existing PAPER_ACTIVE when promoting a new one. Partial UNIQUE index `idx_one_paper_active` enforces DB-level constraint. `TestActiveModelRegistry0344` adds 4 tests. 847 tests pass.
