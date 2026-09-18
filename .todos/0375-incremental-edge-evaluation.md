# Measure Incremental Learning Value Over Base Strategy

- **ID:** 0375
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0374

## Problem

The 0365 prospective gate requires positive ranking spread and MAE ≤ baseline, but
it evaluates `challenger_score` (base + learned adjustment) rather than isolating the
learned adjustment's contribution. A model that earns a positive ranking spread may
still be degrading the base strategy's already-good ordering. The relevant scientific
question is incremental: does the learning component add value over the unchanged
base score? Without a side-by-side comparison on identical candidate cohorts, it's
impossible to tell whether the learner helps or hurts.

## Proposed approach

At prediction time, `score_for_observe()` already has access to both `base_score`
(pre-adjustment composite) and `challenger_score` (post-adjustment). Record both so
prospective evaluation can compute:

```
base_ranking_spread      = top-quintile base_score mean alpha
                         - bottom-quintile base_score mean alpha

challenger_ranking_spread = top-quintile challenger_score mean alpha
                          - bottom-quintile challenger_score mean alpha

incremental_ranking_spread = challenger_ranking_spread - base_ranking_spread

base_selected_mean_alpha     = mean outcome for base-selected candidates
challenger_selected_mean_alpha = mean outcome for challenger-selected candidates
selection_alpha_delta = challenger_selected_mean_alpha - base_selected_mean_alpha
```

Add `base_score` to `model_observations` (already present; verify it is always
populated). Add `base_ranking_spread`, `challenger_ranking_spread`,
`incremental_ranking_spread`, and `selection_alpha_delta` to
`compute_prospective_metrics()` output.

For OBSERVE→PAPER_ACTIVE promotion, add a gate:
```
incremental_ranking_spread >= 0
```
(or warn if negative). This directly answers whether the learner adds value.

Open question: how many independent candidates are required before the incremental
spread estimate is meaningful? Candidates from the same day are correlated.

## Touches

- `agents/learning/calibration.py` — `compute_prospective_metrics()`: add incremental
  metrics; add `incremental_ranking_spread >= 0` to `_check_promotion_gates()`
- `agents/learning/challenger.py` — `score_for_observe()`: confirm `base_score` is
  always populated in the INSERT
- `tests/test_calibration.py` — test that model with negative incremental spread is
  flagged; test that incremental metrics appear in `compute_prospective_metrics()`

## Done when

- [ ] `compute_prospective_metrics()` returns `base_ranking_spread`,
  `challenger_ranking_spread`, `incremental_ranking_spread`, `selection_alpha_delta`
- [ ] OBSERVE→PAPER_ACTIVE gate warns (or blocks) when `incremental_ranking_spread < 0`
- [ ] Test: challenger that beats baseline but degrades base ranking is detected
- [ ] `python -m pytest tests/` passes with no regressions
