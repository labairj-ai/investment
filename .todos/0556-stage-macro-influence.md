# Stage Macro Influence Gradually After Evidence

- **ID:** 0556
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** normal
- **Depends:** 0555

## Problem

Positive experiment results should earn bounded influence incrementally rather than changing production recommendations abruptly.

## Proposed approach

- Define stages: observe-only, near-tie breaker, bounded score adjustment, learned bounded weight, and broader influence.
- Cap every adjustment and require explicit promotion gates between stages.
- Keep dimension ablations available so influence can be assigned only where evidence supports it.

## Done when

- [x] Each stage has a tested cap, rollback path, and promotion criterion.
- [x] No stage changes production behavior without an accepted experiment result.
- [x] Rates/inflation/dollar/geopolitical ablations inform dimension-specific promotion.


## Implementation

Implemented by the observe-only macro experiment, versioned protocol, automatic episode/cohort capture, immutable labels and Learning Lab report. See [design and operations](../docs/macro-value-experiment.md) and `tests/test_macro_experiment.py`.

Completion here means the software and policy are implemented. It does not mean macro effectiveness is established or production influence is approved. Usable prospective collection is constrained by the current opportunity-coverage gap tracked in 0557.
