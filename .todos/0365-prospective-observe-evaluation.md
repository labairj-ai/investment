# Add Prospective Performance Gate to OBSERVE Promotion

- **ID:** 0365
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0360

## Problem

The OBSERVE→PAPER_ACTIVE gate requires `mature_observations >= 5` (rows in
`model_observations` where `outcome_alpha_90d IS NOT NULL`), but it does not
ask whether those predictions were any good. A model that fails every
prospective prediction still satisfies the gate as long as the retrospective
`alpha_edge_evidence` (from training-time walk-forward CV) is POSITIVE. The
two metrics are independent: a model can look good in-sample and fail
completely out-of-sample. Until the gate verifies prospective ranking quality,
promotion to PAPER_ACTIVE proves nothing about live performance.

The critical signal is not precise alpha prediction but ranking quality:
did the model correctly rank better opportunities above worse ones?

## Proposed approach

### 1. Compute prospective metrics after each labeling run

After `outcome_labeler.py` back-fills `outcome_alpha_90d` into
`model_observations`, compute and store a summary for each model version:

| Metric | How |
|---|---|
| `prospective_n` | COUNT rows with outcome_alpha_90d NOT NULL |
| `prospective_selected_n` | COUNT rows where would_select=1 and outcome NOT NULL |
| `prediction_mae` | mean(|challenger_score − outcome_alpha_90d|) for labeled rows |
| `baseline_mae` | mean(|mean_alpha − outcome_alpha_90d|) — naive baseline |
| `prediction_vs_actual_corr` | Pearson r between challenger_score and outcome_alpha_90d |
| `would_select_mean_alpha` | mean(outcome_alpha_90d) where would_select=1 |
| `nonselected_mean_alpha` | mean(outcome_alpha_90d) where would_select=0 |
| `selection_alpha_spread` | would_select_mean_alpha − nonselected_mean_alpha |
| `top_quintile_mean_alpha` | mean outcome for top-20% challenger_score rows |
| `bottom_quintile_mean_alpha` | mean outcome for bottom-20% challenger_score rows |
| `prospective_ranking_spread` | top_quintile_mean_alpha − bottom_quintile_mean_alpha |
| `prospective_hit_rate` | fraction where would_select=1 rows beat median outcome |

Store in a new `model_prospective_metrics` table keyed on `model_version` or
as a JSON blob in `learning_models.prospective_metrics_json`. JSON blob is
simpler and avoids a migration for each new metric.

### 2. Update the OBSERVE→PAPER_ACTIVE gate in `_check_promotion_gates()`

Proposed minimum rule (paper, not live — don't require statistical significance):

```
mature_observations >= 20
AND prospective_selected_n >= 5
AND prospective_ranking_spread > 0
AND prediction_mae <= baseline_mae  (model not worse than naive mean)
AND prospective_edge_evidence != NEGATIVE  (recomputed from observations, not CV)
```

A separate `prospective_edge_evidence` label should be derived from
`selection_alpha_spread` or `prospective_ranking_spread`, not imported from
retrospective `alpha_edge_evidence`. They measure different things.

### 3. Option: PAPER_ACTIVE_EXPERIMENTAL for faster iteration

If the 20-observation requirement is too slow (each takes 90 days to mature),
add a `PAPER_ACTIVE_EXPERIMENTAL` lifecycle state requiring only 5 mature
observations. Models in this state are explicitly blocked from any future
live-capital stage until prospective_n >= 20 and the full gate passes.

### Open questions

- Should `prospective_edge_evidence` use a bootstrap CI over observations, or
  is a simple sign check on `selection_alpha_spread` enough for paper stage?
- Should recomputed metrics invalidate an already-PAPER_ACTIVE model, or only
  block new promotions?

## Touches

- `agents/learning/calibration.py` — `_check_promotion_gates()` new gate
  clauses; `prospective_edge_evidence` computation; optional
  `PAPER_ACTIVE_EXPERIMENTAL` state constant
- `agents/learning/outcome_labeler.py` — trigger metric recomputation after
  back-filling `outcome_alpha_90d` rows
- `agent_db.py` — add `prospective_metrics_json TEXT` column to
  `learning_models` via `_new_cols`; optionally new `model_prospective_metrics`
  table
- `tests/test_calibration.py` — tests that gate fails when ranking_spread ≤ 0,
  that gate passes when all prospective criteria met, that prospective_edge_evidence
  is derived from observations not CV

## Done when

- [ ] `prospective_metrics_json` (or equivalent table) computed after each labeling run
- [ ] `selection_alpha_spread` and `prediction_mae <= baseline_mae` verified for each model_version
- [ ] OBSERVE→PAPER_ACTIVE gate rejects a model that satisfies mature_observations but has ranking_spread <= 0
- [ ] `prospective_edge_evidence` is derived from `model_observations`, not from walk-forward CV
- [ ] Gate requires `prospective_selected_n >= 5` (model actually would-have-picked things)
- [ ] Tests: gate fails on poor ranker, passes on good ranker, prospective_edge_evidence independent of alpha_edge_evidence
- [ ] `python -m pytest tests/` passes with no regressions
