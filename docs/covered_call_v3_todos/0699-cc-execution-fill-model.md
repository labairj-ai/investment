# Calibrate Covered Call Execution and Fill Model

- **ID:** 0699
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0690

## Problem

Entry economics currently use a static execution estimate such as bid plus a fixed fraction of the spread. Actual fill quality varies with spread width, option activity, DTE, moneyness, volatility, and time of day.

Expected roll cost also requires realistic two-leg execution friction.

## Proposed approach

Persist at recommendation and execution time:

- bid
- ask
- mid
- spread dollars
- spread percentage
- open interest
- volume
- IV
- DTE
- delta/moneyness
- recommendation timestamp
- execution timestamp
- underlying price movement during fill window
- execution price
- fees

For short-call fills calculate:

`fill_fraction = (fill - bid) / (ask - bid)`

Build empirical execution buckets by liquidity characteristics.

Before minimum N is reached, use conservative static assumptions.

After minimum N, use shrinkage toward the conservative prior rather than raw bucket means.

Expose:

- `expected_entry_slippage`
- `expected_exit_slippage`
- `expected_roll_slippage`
- `execution_model_version`

## Guardrails

- Do not train on estimated fills as if they were real.
- Separate quote snapshot from actual execution.
- Require minimum N and shrinkage before empirical estimates influence production.
- Handle zero/crossed spreads explicitly.

## Done when

- [ ] Recommendation snapshots include all execution features.
- [ ] Actual fills can be reconciled against contemporaneous quote data.
- [ ] Fill-fraction calibration is queryable by bucket.
- [ ] Low-N buckets fall back to conservative priors.
- [ ] Expected execution cost can feed 0694 utility.
- [ ] Roll execution estimates account for both legs and fees.
