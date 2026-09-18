# Fix Data Health Coverage Denominator and Wire to Promotion

- **ID:** 0380
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0376, 0379

## Problem

`compute_data_health()` has three bugs that make it an unreliable gate. First, the 3-month coverage denominator counts all episodes regardless of age, so a system continuously ingesting new data will always look unhealthy — episodes captured yesterday cannot possibly have 3-month outcomes yet. Second, the aggregate `COUNT(*)` on `episode_outcomes` double-counts episodes once both `calendar_v1` and `sessions_v2` rows exist for the same episode. Third, `_check_promotion_gates()` never calls `compute_data_health()`, so a dataset that develops a `block` condition after training still allows `OBSERVE → PAPER_ACTIVE` promotion.

## Proposed approach

- **Fix denominator**: count only horizon-eligible episodes — for `calendar_v1`, episodes captured >= 91 calendar days ago; for `sessions_v2`, episodes captured >= 63 completed trading sessions ago. Coverage = (labeled outcomes / eligible episodes).
- **Fix double-count**: replace `COUNT(*)` aggregate with `COUNT(DISTINCT episode_id)`, or remove the aggregate metric entirely since per-version counts are more meaningful.
- **Make health target-aware**: add `target_horizon_version` parameter to `compute_data_health()`. The target version is a hard gate; the other version is informational only. A `calendar_v1` model should not be blocked by poor `sessions_v2` coverage, and vice versa.
- **Wire into promotion**: call `compute_data_health(target_horizon_version=model.training_horizon_version)` inside `_check_promotion_gates()` and add `data_health_block` to the failed gates when `overall == "block"`.

## Touches

- `agents/learning/calibration.py` — `compute_data_health()`, `_check_promotion_gates()`, `train_and_save()`
- `tests/test_calibration.py` — coverage denominator tests, promotion gate tests

## Done when

- [ ] Coverage denominator excludes episodes too young to have matured outcomes for the target horizon
- [ ] No double-counting of episodes when both horizon versions exist
- [ ] `compute_data_health()` accepts `target_horizon_version` and gates only on the target version
- [ ] `_check_promotion_gates()` calls `compute_data_health()` and fails on `block`
- [ ] Training a `calendar_v1` model is not blocked by `sessions_v2` health and vice versa
- [ ] `python -m pytest tests/` passes with no regressions
