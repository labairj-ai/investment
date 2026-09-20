# Enforce NOT_EVALUABLE as a Promotion Blocker

- **ID:** 0381
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0375, 0378

## Problem

Two promotion gates in `_check_promotion_gates()` currently treat missing evidence as a pass: `incremental_ranking_spread=None` passes `incremental_ranking_non_negative`, and `n_cohort_days=0` passes `cohort_day_diversity`. This was an intentional backward-compatibility concession for existing observations that predate `base_score` and `scored_at_date`. However, the same logic applies to any newly trained model before it has accumulated real prospective evidence, meaning a brand-new model with zero cohort days and no base scores can advance to `PAPER_ACTIVE` without any incremental or cohort validation at all. Unknown evidence is not passing evidence.

## Proposed approach

- Replace the binary `pass: bool` gate structure with a three-state result: `PASS`, `FAIL`, `NOT_EVALUABLE`.
- `NOT_EVALUABLE` should block promotion to `PAPER_ACTIVE`, the same as `FAIL`.
- Distinguish between old observations (model trained before `base_score`/`scored_at_date` fields existed — truly unevaluable legacy rows) and new models that simply haven't waited long enough. The key signal: if the model's `created_at` postdates the 0378 deployment, `NOT_EVALUABLE` is the correct state; if the model is older, `NOT_EVALUABLE` on legacy rows could remain permissive (or still block — choose explicitly).
- Update gate reporting in the API/dashboard to surface `NOT_EVALUABLE` distinctly from `FAIL` so the operator understands whether to wait or investigate.
- Remove the `test_none_incremental_spread_passes_gate` test (or update it to assert `NOT_EVALUABLE` blocks).

## Touches

- `agents/learning/calibration.py` — `_check_promotion_gates()`, gate result structure
- `tests/test_calibration.py` — update/remove tests that assert `None`-spread passes gate

## Done when

- [ ] Gate results have three states: `PASS`, `FAIL`, `NOT_EVALUABLE`
- [ ] `NOT_EVALUABLE` blocks `OBSERVE → PAPER_ACTIVE` promotion
- [ ] A newly trained model with no `base_score` observations cannot reach `PAPER_ACTIVE`
- [ ] A newly trained model with fewer than `OBSERVE_MIN_COHORT_DAYS` distinct scored dates cannot reach `PAPER_ACTIVE`
- [ ] Gate report distinguishes `NOT_EVALUABLE` from `FAIL`
- [ ] `python -m pytest tests/` passes with no regressions
