# Build Systematic Macro Scorer Repeatability and Calibration Harness

- **ID:** 0479
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0473, 0475, 0478

## Problem

The only runtime quality check currently in place is a single warning message comparing the measured rate beta to the LLM score — a one-line log statement that fires during production scoring, not a systematic validation harness. There is no way to answer: how stable are scores when inputs are frozen, are known anchor instruments scored in sensible relative order, do deterministic factor betas agree with LLM scores, and are week-over-week structural score changes driven by genuine evidence changes or by model noise? Until these questions are answered, feeding macro scores into any automated system is a leap of faith.

## Proposed approach

Build `scripts/validate_macro_scorer.py` (replacing the stub from 0471) with four distinct test modules:

1. **Repeatability** — freeze a macro context snapshot and a company evidence snapshot; call the scoring system N=20 times with identical inputs; for each ticker × dimension compute mean and stddev; write per-dim results to output; flag any dim where stddev > 1.0 as UNSTABLE.

2. **Anchor calibration** — define a small set of instruments with known expected relative order (not absolute scores, which would be overfitting):
   - BIL (3-month T-bill): rate_sensitivity expected ≤ 3
   - VNQ (REIT): rate_sensitivity expected ≥ 7
   - domestic utility (e.g. NEE or similar): dollar_sensitivity expected ≤ 3
   - large multinational >50% foreign revenue: dollar_sensitivity expected ≥ 6
   Score each anchor; report actual vs expected bracket; flag violations.

3. **Factor vs LLM concordance** (runs only when 0473 is complete and betas are available) — for tickers that have `rate_beta_100bp_return_pct`, compare sign and rough magnitude to LLM `rate_sensitivity`; report concordance rate (sign agreement %) and mean absolute score error relative to a simple linear rescaling.

4. **Unexplained structural-score change detection** — compare the two most recent `holding_macro_scores_history` rows per ticker; if evidence hash (from 0475) did not change but score changed by > 1 point on any dimension, flag as UNEXPLAINED_DRIFT.

Output: `out/macro_validation_results.json` with structure `{repeatability: {...}, anchors: {...}, concordance: {...}, drift: {...}, summary: {pass, warn, fail}}`. Print a human-readable table to stdout. Exit code 1 if any FAIL items.

## Touches

- `scripts/validate_macro_scorer.py` (new or replacement of 0471 stub)
- `portfolio_ai.py` (may need a frozen-input scoring entry point)
- `out/macro_validation_results.json`

## Done when

- [x] Repeatability test runs N=20 passes on frozen inputs and reports per-dim stddev
- [x] Anchor calibration test covers at least rate_sensitivity and dollar_sensitivity with expected brackets
- [x] Factor-vs-LLM concordance module runs without error (can skip gracefully if betas unavailable)
- [x] Unexplained drift detection compares last two history rows per ticker by evidence hash
- [x] Results written to `out/macro_validation_results.json`; exit code 1 on any FAIL
