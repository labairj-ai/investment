# Feature-Source Consistency

- **ID:** 0422
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0411

## Problem

`candidate_learning_features()` currently makes canonical keys (`q_score`) win over the OH
underscore aliases (`_q`) when both are present. But for live OH candidates, the underscore
fields (`_q/_v/_pf/_c/_ec`) are the values actually computed by the current sweep, while
`q_score` might be a stale value from a different candidate source or a previous database read.
The current precedence means a future caller that passes a candidate with both sets of keys
could silently cause the model to evaluate one feature vector while the episode DB records
another.

## Proposed approach

Option A (preferred): Invert precedence so `_q/_v/_pf/_c/_ec` win when present (OH sweep
values are authoritative).

Option B: When both canonical and alias keys are present for a given feature, assert they are
equal (within floating-point tolerance). Raise or log ERROR if they diverge. This catches
callers passing inconsistent data without changing existing behavior for consistent callers.

Either option should be accompanied by a test that:
- Passes a candidate with `q_score=90, _q=10` and verifies which value is used
- Documents the choice explicitly in the function docstring

Note: Option A is a behavior change from 0411 and requires updating `test_predict_alpha_canonical_wins_over_alias`
in TestCanonicalFeatureAdapter0411.

## Touches

- `agents/learning/calibration.py` — `candidate_learning_features()` precedence or assertion
- `tests/test_calibration.py` — update 0411 canonical-wins test; add divergence test

## Done when

- [ ] The precedence rule is explicit and documented in `candidate_learning_features()` docstring
- [ ] Either OH underscore keys win, OR a divergence between alias and canonical raises/logs
- [ ] Tests cover the divergence case and confirm which value the model evaluates
