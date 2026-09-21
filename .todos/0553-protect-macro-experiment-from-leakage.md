# Protect the Prospective Macro Experiment From Leakage

- **ID:** 0553
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0549, 0552

## Problem

The macro ablation is only credible if both arms use information available at the original decision timestamp and the same opportunity universe.

## Proposed approach

- Require scores to predate decisions and dimensions to be eligible under the active acceptance.
- Start a new experiment epoch for every scorer-contract change.
- Prohibit retrospective rescoring of primary cohorts and exclude failed outcome labels.
- Keep candidate universe, decision-date embargo, and cohort grouping identical between arms.

## Done when

- [x] Timestamp, contract, eligibility, and opportunity-universe checks are enforced.
- [x] Contract changes create separate epochs.
- [x] Leakage and retrospective-rescore regression tests pass.


## Implementation

Implemented by the observe-only macro experiment, versioned protocol, automatic episode/cohort capture, immutable labels and Learning Lab report. See [design and operations](../docs/macro-value-experiment.md) and `tests/test_macro_experiment.py`.

Completion here means the software and policy are implemented. It does not mean macro effectiveness is established or production influence is approved. Usable prospective collection is constrained by the current opportunity-coverage gap tracked in 0557.
