# Validate Macro Scorer Stability and Validity Before Integration

- **ID:** 0471
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0465, 0467, 0470

## Problem

The macro scoring system has never been tested for repeatability or validity before being connected to downstream consumers. If the same frozen inputs produce materially different scores on repeated runs, the scores contain LLM sampling noise that should not be treated as signal. If anchor instruments score outside expected ranges, the 1–10 scale is not calibrated. Neither property has been measured, which means connecting the macro system to the Learning Lab or Risk Engine risks injecting unchecked noise into those pipelines.

## Proposed approach

Run four validation experiments using a frozen macro snapshot and a fixed set of test tickers (do not use live data during validation):

1. **Repeatability test**: run the exact same frozen macro context + ticker list through the scorer N times (suggest N=10); compute mean and standard deviation per ticker per dimension; flag any dimension where stddev > 1.0 as unstable
2. **Anchor calibration test**: score a set of known-anchor instruments with expected values:
   - Rate sensitivity: 3-month T-bill / cash ≈ 1; leveraged long-duration REIT-like ≈ 10; stable low-debt consumer staple ≈ 3
   - USD sensitivity: pure domestic utility ≈ 1–2; multinational with >60% foreign revenue ≈ 8+
   - Record actual scores vs. expected anchors; flag material deviations
3. **Noise-under-frozen-inputs test**: run the scorer on identical inputs across N consecutive weeks (by replaying the same snapshot); any week-over-week change in scores is pure noise — measure its magnitude
4. **LLM-vs-deterministic comparison** (depends on 0467): for any dimension where a deterministic factor exists, compare the LLM estimate to the measured factor; compute mean absolute error and directional agreement rate

Results should be written to a `macro_validation_results` artifact (JSON or CSV) and summarized in the dashboard or a standalone report.

## Touches

- New validation script (e.g. `scripts/validate_macro_scorer.py`)
- Macro scoring module (need to accept frozen snapshot as input)
- `macro_scoring_runs` ledger from 0470 (log validation runs separately from production runs)

## Done when

- [ ] Repeatability test run for all current holdings; stddev per dimension reported
- [ ] Anchor calibration test run with at least 3 known-anchor instruments per dimension
- [ ] Results artifact written with pass/fail per test
- [ ] Any dimension with stddev > 1.0 or anchor miss > 2 points is explicitly flagged as not suitable for Learning Lab integration
