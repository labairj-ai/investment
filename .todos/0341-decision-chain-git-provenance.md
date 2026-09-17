# Add Git Commit SHA to Decision/Fill Provenance Chain

- **ID:** 0341
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** low
- **Depends:** 0331

## Problem

The system already persists `feature_schema_version`, `model_version`, `strategy_config_hash`, and `policy_hash` independently across the decision chain. But there is no record of which code version was running when a decision was made. Six months later, when a trade behaved unexpectedly, you cannot answer: "Was the logic in `opportunity_agent.py` the same version as two weeks earlier?" Git commit SHA makes that question answerable without excavating logs.

## Proposed approach

- At startup (or per-run), capture `git rev-parse HEAD` and expose it as a module constant (e.g., `agent_db.CODE_COMMIT_SHA`); fall back to `None` if not in a git repo
- Persist it on: `agent_runs.code_commit_sha`, `decision_episodes.code_commit_sha`, `trade_intents.code_commit_sha`
- Do not add it to every table — just the three that anchor the decision chain; downstream rows (orders, fills) inherit provenance via FK
- Add `_new_cols` migration entries for each column (existing rows get NULL, which is fine)

## Touches

- `agent_db.py` — add `code_commit_sha TEXT` to `agent_runs`, `decision_episodes`, `trade_intents` via `_new_cols`; helper function to read SHA at import time
- `agents/opportunity_agent.py` — write SHA to decision episode at capture time
- `trade_engine/intent_builder.py` — write SHA to trade intent
- `tests/` — smoke test that SHA column exists and is non-NULL in a new run

## Done when

- [x] `git rev-parse HEAD` is captured at run time and stored on `agent_runs`, `decision_episodes`, and `trade_intents`
- [x] Graceful fallback to `NULL` when not in a git repo (test environments)
- [x] Postmortem query `SELECT DISTINCT code_commit_sha FROM decision_episodes WHERE captured_at BETWEEN X AND Y` returns meaningful results
- [x] `python -m pytest tests/` passes with no regressions

## Outcome

5 files changed. `agent_db.py`: added `CODE_COMMIT_SHA` module constant (subprocess `git rev-parse HEAD`, None if not in a repo); `code_commit_sha TEXT` added to CREATE TABLE for `agent_runs`, `trade_intents`, `decision_episodes`, and to `_new_cols` migration list for existing DBs; `insert_agent_run()` writes the SHA. `agents/learning/episode_capture.py`: INSERT includes `code_commit_sha`. `trade_engine/models.py`: `TradeIntent` gains `code_commit_sha: Optional[str]` field; `to_db_dict()` and `from_db_row()` updated. `trade_engine/intent_builder.py`: imports `agent_db`; both `build_intent()` and `build_intent_from_variant()` pass `code_commit_sha=agent_db.CODE_COMMIT_SHA`. Tests in `tests/test_trade_engine.py` and `tests/test_broker_contract.py` updated with the new column. 5 new tests in `TestGitShaSHA0341`. 820 passed.
