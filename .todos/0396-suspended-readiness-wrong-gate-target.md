# Fix Readiness Report Evaluating SUSPENDED Models Against Wrong Gate Target

- **ID:** 0396
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** none

## Problem

`learning_readiness_report()` calls `_check_promotion_gates(model_version, LIFECYCLE_PAPER_ACTIVE)` for models in both OBSERVE and SUSPENDED lifecycle states. However, SUSPENDED models cannot transition directly to PAPER_ACTIVE — they must go through OBSERVE first (`valid_transitions` in `promote()` only allows SUSPENDED → OBSERVE). Presenting PAPER_ACTIVE gate results for a SUSPENDED model misleads the operator into thinking those gates are the blocker, when the correct question is whether the model is ready to re-enter OBSERVE.

## Proposed approach

- In `learning_readiness_report()`, separate the gate target by lifecycle:
  - `OBSERVE` → evaluate `_check_promotion_gates(model_version, LIFECYCLE_PAPER_ACTIVE)` (correct, unchanged)
  - `SUSPENDED` → evaluate `_check_promotion_gates(model_version, LIFECYCLE_OBSERVE)` (or show "not evaluable for direct promotion — must re-enter OBSERVE")
  - Other states → no gate evaluation (PAPER_ACTIVE, TRAINED don't have standard promotion gate paths here)
- Return `promotion_target_state` in the readiness report so the dashboard can label the gates correctly.
- Update the `/api/learning/readiness` dashboard card to show the actual target state name.

## Touches

- `agents/learning/calibration.py` — `learning_readiness_report()` lines ~1503-1507
- `serve.py` — `_handle_learning_readiness()` (minor)
- `generate_dashboard.py` — readiness card JS (label the gate target)
- `tests/test_calibration.py` — `TestLearningReadinessReport0385`

## Done when

- [ ] SUSPENDED models evaluated against `LIFECYCLE_OBSERVE` gates, not PAPER_ACTIVE
- [ ] `promotion_target_state` key returned in readiness report
- [ ] Dashboard card labels gate section with the actual target state
- [ ] Test covers SUSPENDED lifecycle and asserts gate target is OBSERVE
- [ ] Full test suite passes
