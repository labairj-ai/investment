# Add a Macro Effectiveness Panel to Learning Lab

- **ID:** 0554
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** normal
- **Depends:** 0551, 0552, 0553

## Problem

The accepted scorer needs an evidence view in Learning Lab without turning a small sample into a misleading success signal.

## Proposed approach

- Show acceptance/epoch, prospective and divergent cohort counts, matured 90-day cohorts, wins/losses/ties, mean/median delta, bootstrap interval, and evidence state.
- Break down eligible dimensions by N, alpha delta, and MAE.
- Reuse insufficient/inconclusive evidence semantics and keep the panel observe-only.

## Done when

- [x] Dashboard reads the immutable cohort ledger.
- [x] Evidence state cannot become positive without sufficient diversity, divergence, and precision.
- [x] Dimension and regime breakdowns preserve the same eligibility rules.


## Implementation

Implemented by the observe-only macro experiment, versioned protocol, automatic episode/cohort capture, immutable labels and Learning Lab report. See [design and operations](../docs/macro-value-experiment.md) and `tests/test_macro_experiment.py`.

Completion here means the software and policy are implemented. It does not mean macro effectiveness is established or production influence is approved. Usable prospective collection is constrained by the current opportunity-coverage gap tracked in 0557.
