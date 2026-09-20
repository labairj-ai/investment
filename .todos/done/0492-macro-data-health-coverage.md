# Add Macro Data Health and Portfolio Coverage Report

- **ID:** 0492
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0486, 0487

## Problem

The Macro Risk dashboard shows scores per holding but has no top-level summary of how much of the portfolio actually has supported exposure data. A portfolio with 70% of value in unsupported funds displaying a confident-looking composite score is misleading. Additionally there is no operational health view: latest scoring run status, stale/missing macro series, weak-beta count, or unexplained structural-drift count. Learning Lab will eventually need this quality context alongside any macro features it captures.

## Proposed approach

Add a "Macro Data Health" card to the Macro Risk tab (or as a collapsible section near the top) showing:

- **Last successful scoring run**: run_id, run_at, scored_n / expected_n, status
- **Portfolio macro coverage**: `% of portfolio value with supported company evidence` (exclude unsupported funds from numerator; show count and value weight separately)
- **Stale macro series**: list any MacroMeasurement where `stale=True`
- **Missing/UNKNOWN regime fields**: list regime dimensions currently UNKNOWN
- **Weak beta count**: tickers where `rate_beta_confidence == "weak"` or `"insufficient_data"`
- **Unexplained structural drift**: count of tickers with score change > 1pt and unchanged evidence hash in last two runs
- **Unsupported instruments**: list of fund tickers with `evidence_quality = "unsupported"`

This data should also be stored as a JSON blob in a new `macro_health_snapshots` table so Learning Lab can later join quality flags to episodes.

## Touches

- `generate_dashboard.py` — Macro Risk tab health card
- `portfolio_ai.py` — health snapshot computation and `macro_health_snapshots` table
- Dashboard HTML/CSS — health card layout

## Done when

- [ ] Macro Risk tab shows portfolio-value coverage % (supported companies vs. total)
- [ ] Health card lists stale macro series and UNKNOWN regime fields
- [ ] Weak beta count and unexplained drift count visible
- [ ] `macro_health_snapshots` table stores JSON health snapshot per scoring run
- [ ] Learning Lab integration can join health snapshot by run_id
