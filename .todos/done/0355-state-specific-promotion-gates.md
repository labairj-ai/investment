# State-Specific Promotion Gates per Lifecycle Transition

- **ID:** 0355
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0348

## Problem

`_check_promotion_gates()` applies the same gate set regardless of whether the transition is TRAINED→OBSERVE or OBSERVE→PAPER_ACTIVE. A model can pass OBSERVE gates and immediately pass PAPER_ACTIVE gates with zero observation time elapsed, making OBSERVE a no-op state. Gates also require only `cv_folds >= 1`; a single walk-forward fold is not meaningful statistical evidence. `beats_baseline` compares against mean-alpha, which a trivially overfit model can achieve with one fold.

## Proposed approach

**TRAINED → OBSERVE** (offline statistical gate):
- `unique_tickers >= 10`, `unique_decision_dates >= 30`, `unique_weeks >= 4` (existing)
- `cv_folds >= 3` (raise from 1)
- `beats_baseline is True`
- `alpha_edge_evidence != "NEGATIVE"` (not actively destructive)

**OBSERVE → PAPER_ACTIVE** (observation gate, requires lived time):
- All TRAINED→OBSERVE gates must still pass on current data
- Minimum elapsed time in OBSERVE state: 14 calendar days (configurable constant `OBSERVE_MIN_DAYS = 14`)
- At least 5 fresh decision episodes since the model entered OBSERVE (episodes captured_at > promote_to_observe_time)
- `alpha_edge_evidence` is `"POSITIVE"` or `"INCONCLUSIVE"` (not `"NEGATIVE"`)
- No schema/feature version mismatch between model and current episodes

**Implementation:**
- `_check_promotion_gates(model_version, target_state)` branches on `target_state` for different gate sets
- For OBSERVE→PAPER_ACTIVE, read `model_promotion_log` for the OBSERVE transition timestamp; compute elapsed days; count fresh episodes since then
- Store `OBSERVE_MIN_DAYS = 14` as a module constant so it can be adjusted

## Touches

- `agents/learning/calibration.py` — `_check_promotion_gates()` branched by target_state; new OBSERVE→PAPER_ACTIVE checks; `OBSERVE_MIN_DAYS` constant; `cv_folds >= 3`
- `tests/test_calibration.py` — test OBSERVE→PAPER_ACTIVE blocked when model promoted to OBSERVE < 14 days ago; test `cv_folds=1` blocked at TRAINED→OBSERVE

## Done when

- [ ] `cv_folds >= 3` required for TRAINED→OBSERVE (not 1)
- [ ] OBSERVE→PAPER_ACTIVE requires at least `OBSERVE_MIN_DAYS` elapsed since OBSERVE promotion
- [ ] OBSERVE→PAPER_ACTIVE requires at least 5 fresh episodes captured after OBSERVE start
- [ ] `alpha_edge_evidence = "NEGATIVE"` blocks OBSERVE→PAPER_ACTIVE
- [ ] Test: model promoted to OBSERVE today cannot immediately promote to PAPER_ACTIVE
- [ ] `python -m pytest tests/` passes with no regressions
