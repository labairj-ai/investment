# Pre-Register Macro Effectiveness Metrics

- **ID:** 0551
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0550

## Problem

The experiment needs a fixed definition of value before prospective outcomes are observed.

## Proposed approach

- Make primary metric mean 90-day SPY-relative selection delta among divergent cohorts.
- Define secondary wins, losses, ties, median delta, bootstrap confidence intervals, 1-week/1-month outcomes, MFE/MAE, virtual-book return/drawdown/volatility, concentration, turnover, and churn.
- Keep 90-day alpha as the graduation metric; early horizons are diagnostics only.

## Done when

- [x] Metric definitions, horizons, exclusions, and bootstrap procedure are versioned before analysis.
- [x] Outcome-label failures produce unevaluable cohorts.
- [x] No post-hoc metric or sample-size changes are permitted.


## Implementation

Implemented by the observe-only macro experiment, versioned protocol, automatic episode/cohort capture, immutable labels and Learning Lab report. See [design and operations](../docs/macro-value-experiment.md) and `tests/test_macro_experiment.py`.

Completion here means the software and policy are implemented. It does not mean macro effectiveness is established or production influence is approved. Usable prospective collection is constrained by the current opportunity-coverage gap tracked in 0557.
