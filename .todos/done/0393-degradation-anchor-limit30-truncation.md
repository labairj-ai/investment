# Fix Hysteresis Anchor Truncation from LIMIT 30 Window

- **ID:** 0393
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** none

## Problem

`_check_degradation()` fetches the 30 most recent observations (`ORDER BY id DESC LIMIT 30`) and then computes `current_max_labeled_at = max(labeled_at_vals)` from that window. If more than 30 outcomes were labeled in a burst (e.g. outcome labeler back-fills a batch), the true maximum `outcome_labeled_at` across all rows can be higher than the max within the LIMIT-30 window. The stored anchor is silently truncated, causing the next snapshot's hysteresis window to start too early — it counts outcomes already counted in the previous snapshot, potentially firing a new snapshot prematurely.

## Proposed approach

- Compute `current_max_labeled_at` from a separate targeted query instead of deriving it from the LIMIT-30 window:
  ```sql
  SELECT MAX(outcome_labeled_at) FROM model_observations
  WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
    AND (observation_phase='PAPER_ACTIVE' OR observation_phase IS NULL)
  ```
- The LIMIT-30 window is still correct for metric computation (we want the rolling window, not all time); only the anchor derivation needs to change.
- Add a test that seeds >30 labeled outcomes at different timestamps and asserts the stored `last_outcome_labeled_at` equals the global max, not the max within 30.

## Touches

- `agents/learning/calibration.py` — `_check_degradation()` lines ~1364-1368
- `tests/test_calibration.py` — `TestOutcomeTimeHysteresis0384`

## Done when

- [ ] `current_max_labeled_at` is computed via a global MAX query, independent of LIMIT-30 window
- [ ] Test seeds >30 outcomes; asserts anchor equals global max
- [ ] Full test suite passes
