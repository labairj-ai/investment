# Define Macro Experiment Graduation Criteria

- **ID:** 0555
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** normal
- **Depends:** 0551, 0552, 0553

## Problem

The experiment needs evidence-based graduation criteria without an arbitrary episode count.

## Proposed approach

- Require diversity across dates, tickers, sectors, and regimes; sufficient divergent cohorts; and statistical precision from date-clustered bootstrap intervals.
- Use preliminary milestones only for reporting, not proof.

## Done when

- [x] Graduation requires effect direction, uncertainty, diversity, and risk checks.
- [x] No fixed magic N is treated as proof.


## Implementation

Implemented by the observe-only macro experiment, versioned protocol, automatic episode/cohort capture, immutable labels and Learning Lab report. See [design and operations](../docs/macro-value-experiment.md) and `tests/test_macro_experiment.py`.

Completion here means the software and policy are implemented. It does not mean macro effectiveness is established or production influence is approved. Usable prospective collection is constrained by the current opportunity-coverage gap tracked in 0557.
