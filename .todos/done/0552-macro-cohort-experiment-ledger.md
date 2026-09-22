# Persist the Macro Cohort Experiment Ledger

- **ID:** 0552
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0550, 0551

## Problem

The decision cohort, rather than each candidate row, is the experimental unit for measuring selection value.

## Proposed approach

- Persist cohort ID/date, control and macro episode IDs/tickers/scores, divergence, dimensions used, acceptance record, 1-week/1-month/90-day deltas, and maturity.
- Reuse existing divergent-cohort and virtual-book infrastructure.

## Done when

- [x] One immutable row represents each control/macro cohort comparison.
- [x] Maturity and evaluability are explicit.
- [x] Reports distinguish macro wins, control wins, ties, and unevaluable cohorts.


## Implementation

Implemented by the observe-only macro experiment, versioned protocol, automatic episode/cohort capture, immutable labels and Learning Lab report. See [design and operations](../docs/macro-value-experiment.md) and `tests/test_macro_experiment.py`.

Completion here means the software and policy are implemented. It does not mean macro effectiveness is established or production influence is approved. Usable prospective collection is constrained by the current opportunity-coverage gap tracked in 0557.
