# Build Decision Episode and Candidate Observation Layer

- **ID:** 0327
- **Status:** done
- **Created:** 2026-09-15
- **Priority:** normal
- **Depends:** 0315

## Problem

The system discards all scoring data for candidates it does not select: every cycle, Q/V/PF/C/EC vectors, raw fundamentals, LLM conviction, and candidate rank are computed for every stock but only the winner survives. Non-selected candidates are the most valuable training signal for a future learning loop — you can label them retrospectively against market outcomes — but they are being silently thrown away. Additionally, executed_actions stores only BUY/SELL side, losing the original recommendation semantics (TRIM vs EXIT are both SELL but are entirely different decisions). Without both fixes, a trustworthy machine-learning dataset cannot be reconstructed from historical data.

## Proposed approach

**Step 1 — Schema migration (no behavior changes):**
- Add `decision_episodes` table: episode_id, recommendation_id, run_id, ticker, timestamp, candidate_rank, selected (bool), Q/V/PF/C/EC components, composite, raw fundamentals (Buffett score, P/E, P/FCF, valuation percentiles, margins, FCF), LLM conviction stars, model/prompt version, portfolio snapshot (weight, layer, sector concentration, cash), macro snapshot (SPY regime, volatility, rates), feature_schema_version, strategy_hash.
- Add `episode_outcomes` table: episode_id, horizon (1w/1m/3m/6m/12m), ticker_return, spy_return, alpha, mae, mfe, labeled_at.
- Add `learning_models` table: model_version, training_cutoff, feature_schema_hash, training_n, validation_metrics_json, created_at.
- Add `risk_counterfactual_outcomes` table: for tracking prospective returns of risk-rejected intents.
- Add `decision_origin` TEXT column to `trade_intents` (values: USER_ACCEPTED, SHADOW_AUTO, PAPER_AUTO, LIVE_USER, LIVE_AUTO).
- Add `recommendation_action` TEXT column to `executed_actions` to preserve original intent semantics alongside existing `action` (side) column.
- Add `episode_id` FK column to `trade_intents`.

**Step 2 — Candidate capture in opportunity_agent.py:**
- At the candidate scoring loop (~lines 366–384, where Q/V/PF/C/EC are computed per candidate before sorting), call `capture_candidate_episode()` for every candidate, not just the selected one.
- Capture happens before any sorting, thresholding, or LLM call — this is the immutable feature snapshot.
- After LLM returns, back-fill `selected=True` and `llm_conviction` on the winning episode row.
- Create `agents/learning/__init__.py` and `agents/learning/episode_capture.py` with the capture function.

**Open questions:**
- Should the macro/regime snapshot come from a dedicated snapshot helper or be assembled inline at capture time?
- How should episode rows be linked when the LLM rejects all candidates and no recommendation is created?

## Touches

- `db/migrations/` — new migration file for all schema additions
- `agents/opportunity_agent.py` — insert capture call in candidate scoring loop
- `agents/learning/__init__.py` — new file
- `agents/learning/episode_capture.py` — new file
- `tests/` — tests for episode persistence, immutability, and schema migration

## Done when

- [ ] Migration adds `decision_episodes`, `episode_outcomes`, `learning_models`, `risk_counterfactual_outcomes` tables with correct columns
- [ ] `trade_intents` has `decision_origin` column; `executed_actions` has `recommendation_action` column; `trade_intents` has `episode_id` FK
- [ ] `capture_candidate_episode()` is called for every scored candidate in opportunity_agent.py before sorting
- [ ] Captured snapshot is immutable (no updates to fundamentals fields after creation)
- [ ] `selected` and `llm_conviction` are back-filled on the winner episode after LLM returns
- [ ] Existing scoring, sorting, thresholding, and recommendation behavior is unchanged
- [ ] All existing tests pass; new unit tests verify episode rows are created and immutable

## Outcome

Implemented in commit 44a6b90. Four new tables: `decision_episodes`, `episode_outcomes`, `learning_models`, `risk_counterfactual_outcomes`. Three new columns: `trade_intents.decision_origin`, `trade_intents.episode_id`, `executed_actions.recommendation_action`. `agents/learning/episode_capture.py` provides `capture_candidate_episode()` / `update_episode_ranks()` / `mark_episode_selected()`. opportunity_agent.py wired: episodes captured for every scored candidate before sort, ranks updated after sort, winner marked after LLM selection. 10 new tests, 737 total pass. The `portfolio_snapshot_json` field captures `layer_weights` and `held_tickers` at capture time. `llm_conviction` column exists but is NULL until a future agent returns a 1-5 star score.
