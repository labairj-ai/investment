# Make Data Health a Hard Gate on Training and Promotion

- **ID:** 0376
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** none

## Problem

`compute_data_health()` (0370) checks outcome coverage, ticker concentration, MTM
completeness, OBSERVE observation coverage, and feature null rates, then returns an
`overall` verdict of `ok`, `warn`, or `block`. However, `block` is informational only:
nothing in `train_and_save()` or `_check_promotion_gates()` consults `compute_data_health()`
before proceeding. A data-quality problem that should halt training (e.g., 80% null
feature rates, 0% outcome coverage) is silently ignored and the model trains anyway.

Additionally, the 0370 implementation checks feature null rates for column names
`quality_score`, `portfolio_fit_score`, etc., which do not exist in `episode_features`.
The correct column names are `q_score`, `v_score`, `pf_score`, `c_score`, `ec_score`.
This means the null-rate checks always return 0.0 (no nulls found), masking real
sparsity.

## Proposed approach

1. **Fix column names** in `compute_data_health()`: replace `quality_score`,
   `portfolio_fit_score`, `momentum_score` etc. with `q_score`, `v_score`, `pf_score`,
   `c_score`, `ec_score`.

2. **Gate `train_and_save()`**: at the top of the method, call `compute_data_health()`.
   If `overall == "block"`, raise `DataHealthBlockError` (a new exception subclass) with
   the blocking metric names included in the message. Do NOT silently skip training.

3. **Gate `_check_promotion_gates()`**: if `overall == "block"`, add `data_health_block`
   to the failed gate list so OBSERVE→PAPER_ACTIVE is prevented.

4. **Version outcome coverage separately**: the `outcome_coverage` metric currently
   treats all `episode_outcomes` rows equally regardless of horizon version. Add a
   breakdown by `horizon_definition_version` so a health check can distinguish
   "no calendar_v1 outcomes yet" from "no outcomes at all".

## Touches

- `agents/learning/calibration.py` — `compute_data_health()`: fix column names;
  `train_and_save()`: health check at entry point; `_check_promotion_gates()`: consult
  health; add `DataHealthBlockError`
- `tests/test_calibration.py` — test that training is blocked when `overall=="block"`;
  test that health check uses correct column names (`q_score` etc.)

## Done when

- [ ] `compute_data_health()` queries `q_score`, `v_score`, `pf_score`, `c_score`,
  `ec_score` (not the non-existent longer names)
- [ ] `train_and_save()` raises `DataHealthBlockError` when `overall == "block"`
- [ ] `_check_promotion_gates()` adds `data_health_block` to failed gates when
  `overall == "block"`
- [ ] Outcome coverage reported per `horizon_definition_version`
- [ ] Test: seeding null-heavy feature data produces a block verdict; training raises
- [ ] `python -m pytest tests/` passes with no regressions
