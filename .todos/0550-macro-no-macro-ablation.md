# Build an Observe-Only Macro Ablation

- **ID:** 0550
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0549

## Problem

The project needs to measure incremental macro value without changing production recommendations. Control and challenger decisions must differ only by formally eligible macro information.

## Proposed approach

- Run identical candidate sets, timestamps, evidence, model, and risk rules through control and macro arms.
- Keep the experiment shadow-only; do not alter trade-engine behavior or production weights.
- Record lineage for both episodes and identify divergent decisions.

## Done when

- [x] Control and macro arms use identical frozen inputs except eligible macro features.
- [x] Divergent cohorts are explicitly identified and reproducible.
- [x] No production recommendation or execution path changes.


## Implementation

Implemented by the observe-only macro experiment, versioned protocol, automatic episode/cohort capture, immutable labels and Learning Lab report. See [design and operations](../docs/macro-value-experiment.md) and `tests/test_macro_experiment.py`.

Completion here means the software and policy are implemented. It does not mean macro effectiveness is established or production influence is approved. Usable prospective collection is constrained by the current opportunity-coverage gap tracked in 0557.
