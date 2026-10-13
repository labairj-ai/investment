# Covered Call Learning Lab Dashboard

- **ID:** 0703
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** normal
- **Depends:** 0700, 0701, 0702

## Problem

Covered-call model quality will be difficult to reason about if prediction calibration, path outcomes, champion/challenger divergence, and duration/coverage cohorts remain buried in raw database rows.

## Proposed approach

Add a Covered Call Learning Lab view with decision-level and cohort-level diagnostics.

Decision detail should show:

- champion vs challenger action
- contract and overwrite fraction
- V2 score
- V3 utility decomposition
- terminal regret
- strike-touch probability
- delta-threshold probabilities
- realized touch/roll/assignment outcomes
- expected vs realized execution cost
- total CC incremental alpha vs hold
- roll-chain economics

Cohort views should include:

- roll rate by original DTE
- roll rate by entry delta
- roll rate by OTM bucket
- roll rate by overwrite fraction
- incremental alpha by DTE
- incremental alpha by IV/VRP bucket
- outcomes by thesis strategy
- outcomes by regime state
- calibration plots/tables for touch and roll probabilities
- champion/challenger divergence outcomes

All cohort analysis must show N and eligibility/censoring counts.

## Guardrails

- Dashboard is diagnostic, not an independent scoring engine.
- Do not hide low-N cohorts.
- Distinguish predicted, observed, estimated, and censored data.
- Do not imply statistical significance without an explicit test.

## Done when

- [ ] Individual CC decisions can be audited end to end.
- [ ] Cohort tables always show sample size.
- [ ] Roll rate by DTE and entry-delta buckets is available.
- [ ] Incremental alpha vs hold is available by major feature cohort.
- [ ] Probability calibration is visible.
- [ ] Champion/challenger divergence outcomes are visible.
- [ ] Dashboard uses immutable episode/outcome data rather than recomputing historical features with current models.
