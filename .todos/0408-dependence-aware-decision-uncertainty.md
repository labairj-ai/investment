# Dependence-Aware Decision Uncertainty

- **ID:** 0408
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0402

## Problem

The 0402 bootstrap CI resamples individual daily cohort deltas as if they are IID. They are not. Daily Opportunity Hunter sweeps share a 63-session (~3-month) outcome window, so consecutive cohorts' returns overlap almost entirely. Bootstrapping them as independent observations understates uncertainty — the 90% CI will be narrower than the true interval, making POSITIVE evidence appear more reliable than it is. This matters most for governance decisions like PAPER_ACTIVE promotion.

## Proposed approach

Add a block bootstrap alongside the existing IID bootstrap:
- Cluster divergent cohort deltas by decision week (or 5-session blocks of scored_at_date).
- Resample clusters with replacement; compute mean delta per resample.
- Report both intervals in the readiness card:
  - `selection_delta_ci_low_iid` / `selection_delta_ci_high_iid` (current)
  - `selection_delta_ci_low_block` / `selection_delta_ci_high_block`
  - `selection_delta_evidence_block` (POSITIVE/INCONCLUSIVE/NEGATIVE from block CI)

Policy guidance:
- PAPER_ACTIVE promotion can continue to rely on positive incremental ranking spread (not block CI) — block CI may delay experimentation unnecessarily with small samples.
- Any future live-autonomy gate should require positive block-adjusted evidence.
- Surface both intervals in the readiness card so the difference is visible.

Minimum viable: if fewer than 4 distinct decision weeks exist, skip block bootstrap and report `selection_delta_evidence_block = None` (insufficient clustering resolution).

## Touches

- `agents/learning/calibration.py` — `compute_prospective_metrics()` bootstrap section
- Readiness card / API response schema — add `_block` variants
- Tests — block bootstrap with known weekly cluster structure

## Done when

- [ ] Block bootstrap (weekly clusters) is computed alongside IID bootstrap when >= 4 weeks of divergent cohorts exist
- [ ] Both CI variants are returned from `compute_prospective_metrics()`
- [ ] Readiness card displays both intervals
- [ ] Tests cover: fewer than 4 weeks (skip block), exactly 4 weeks, mixed week sizes
- [ ] Documentation note: which interval governs which promotion gate
