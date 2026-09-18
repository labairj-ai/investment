# Label Block Bootstrap as Short-Block Estimate; Plan Stronger Inference

- **ID:** 0417
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** low
- **Depends:** 0408

## Problem

The weekly block bootstrap added in 0408 is better than IID resampling but still materially underestimates dependence. A Sept 1 decision and Sept 8 decision share ~58 of 63 subsequent trading sessions, so adjacent weeks are not independent blocks. Weekly-clustered intervals will generally be too optimistic and should not be used as live-capital governance gates. The statistic is still informative but needs to be clearly labeled to prevent misuse.

## Proposed approach

- Rename the return keys from `selection_delta_ci_{low,high,evidence}_block` to `selection_delta_ci_{low,high,evidence}_short_block` (or add a `block_size_weeks: 1` metadata field) so callers know the block length.
- Add a prose label in readiness report output (e.g. `"block_bootstrap_note": "weekly blocks; adjacent cohorts ~90% correlated; treat as lower bound on uncertainty"`).
- Add a `TODO` comment in the bootstrap code flagging the upgrade path: moving-block bootstrap with ~13-week blocks, stationary bootstrap, or HAC/Newey-West, once enough months of data have accumulated.
- Do **not** use `selection_delta_evidence_block` as a promotion gate criterion until block size is >= 13 weeks.
- When the dataset spans >= 52 weeks of divergent cohorts, re-evaluate whether to upgrade to longer blocks.

## Touches

- `agents/learning/calibration.py` — return key names, readiness report, promotion gate guard
- `tests/test_calibration.py` — update key name assertions
- Dashboard/newsletter rendering if it surfaces block CI labels

## Done when

- [ ] Block bootstrap CI keys are renamed or annotated to communicate the short-block limitation
- [ ] `learning_readiness_report()` includes a human-readable note on block bootstrap limitations
- [ ] Block CI is not wired into any promotion gate criterion
- [ ] A comment in the bootstrap code documents the upgrade path to longer blocks
