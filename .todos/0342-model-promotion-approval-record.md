# Model Promotion Approval Record

- **ID:** 0342
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0335

## Problem

The lifecycle governance from 0335 correctly enforces statistical promotion gates. But there is no record of *why* a model was promoted — only that it met the minimum thresholds. Six months later, you cannot answer: "Why exactly did model edge_v007 get promoted to PAPER_ACTIVE?" The promotion gates tell you it technically qualified; they don't tell you who decided, what the specific metrics were at that moment, or what reasoning was applied. This matters even for paper trading — if a promoted model later underperforms, you want to understand the promotion decision, not just the model metrics.

## Proposed approach

Add explicit approval fields to `learning_models`:
- `promoted_by TEXT` — who or what triggered the promotion (`"manual"`, `"policy_v2"`, a user identifier, etc.)
- `promoted_at REAL` — Unix timestamp of each promotion step (or use a separate `model_promotion_log` table for full history)
- `promotion_reason TEXT` — free-text note captured at promotion time
- `promotion_metrics_snapshot TEXT` — JSON snapshot of all gate metrics at the moment of promotion (not just pass/fail — the actual values: unique_tickers=14, cv_folds=3, beats_baseline=True, etc.)

Recommend a separate `model_promotion_log` table rather than columns on `learning_models`, because a model goes through multiple promotions (TRAINED→OBSERVE, OBSERVE→PAPER_ACTIVE) and columns would need to be duplicated per step.

`promote()` in `calibration.py` should require a `promoted_by` argument (non-optional, `force=True` path included) and write a log row at each successful state transition.

## Touches

- `agent_db.py` — new `model_promotion_log` table: `(id, model_version, from_state, to_state, promoted_by, promoted_at, promotion_reason, promotion_metrics_snapshot)`
- `agents/learning/calibration.py` — `promote()` signature: add `promoted_by: str`, `promotion_reason: str = ""` params; write log row on success
- `tests/test_calibration.py` — assert promotion log row written with correct from/to state and metrics snapshot; assert `promoted_by` is recorded

## Done when

- [ ] `model_promotion_log` table exists with all fields above
- [ ] `promote()` writes a log row for every successful state transition, including `promoted_by`, `promotion_reason`, and a JSON metrics snapshot
- [ ] Query `SELECT * FROM model_promotion_log WHERE model_version=?` gives complete promotion history for any model
- [ ] `python -m pytest tests/` passes with no regressions
