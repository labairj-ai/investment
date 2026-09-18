# Normalize OH Candidate Feature Names Before Challenger Scoring

- **ID:** 0411
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0404

## Problem

The live Opportunity Hunter builds candidate dicts with underscore-prefixed keys (`_q`, `_v`, `_pf`, `_c`, `_ec`) while `ChallengerModel.predict_alpha()` reads the canonical DB column names (`q_score`, `v_score`, `pf_score`, `c_score`, `ec_score`). `capture_candidate_episode()` translates those keys into DB columns but never mutates the in-memory candidate dict. As a result, `predict_alpha()` returns `None` for every live OH candidate, `apply_challenger_adjustment()` applies no learned adjustment, and `score_for_observe()` silently skips every candidate — the shadow learner writes nothing. Unit tests mask the bug because they explicitly seed both key forms.

## Proposed approach

- Add `candidate_learning_features(candidate) -> dict` in `calibration.py` (or a shared util) that reads `q_score or _q`, `v_score or _v`, etc. and returns a normalized dict.
- Call that extractor inside `predict_alpha()` (or at the entry point of both `apply_challenger_adjustment()` and `score_for_observe()`) so all prediction paths use the same resolved feature vector.
- Do **not** scatter duplicate key assignments throughout Opportunity Hunter.
- Add an integration test that constructs an OH-shaped candidate containing only `_q`/`_v`/`_pf`/`_c`/`_ec` (no canonical keys) and asserts `predict_alpha()` returns a non-None float.
- Verify `score_for_observe()` writes at least one row when fed OH-shaped candidates.

## Touches

- `agents/learning/calibration.py` — `predict_alpha()`, new `candidate_learning_features()`
- `agents/learning/challenger.py` — `apply_challenger_adjustment()`, `score_for_observe()`
- `tests/test_calibration.py` — new OH-shape integration tests

## Done when

- [ ] `predict_alpha()` returns a non-None value when called with an OH-shaped dict (`_q`/`_v`/`_pf`/`_c`/`_ec` only)
- [ ] `score_for_observe()` writes model_observations rows when fed OH-shaped candidates
- [ ] `apply_challenger_adjustment()` returns a non-zero adjustment when the model is active and the candidate is OH-shaped
- [ ] New integration test passes using the exact candidate structure Opportunity Hunter produces
- [ ] No duplicate key assignments added to `opportunity_agent.py`
