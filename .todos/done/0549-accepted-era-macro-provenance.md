# Capture Accepted-Era Macro Provenance on Decision Episodes

- **ID:** 0549
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0535

## Problem

Prospective macro evaluation must prove which accepted scorer contract supplied each decision episode's macro features. Historical pre-acceptance episodes remain available, but the primary experiment begins at the v1.7 acceptance boundary.

## Proposed approach

- Persist or immutably link `macro_acceptance_record_id`, `scorer_contract_hash`, `macro_config_version`, `macro_score_timestamp`, prompt/evidence hashes, usable dimensions, and macro coverage state.
- Mark episodes before the acceptance boundary as historical and exclude them from the primary prospective analysis.
- Preserve snapshot immutability and fail closed when provenance is incomplete.

## Done when

- [x] Every prospective episode can identify the exact accepted macro contract and input provenance.
- [x] Accepted-era boundary and pre-acceptance exclusion are tested.
- [x] Missing provenance makes an episode unevaluable rather than imputed.


## Implementation

Implemented by the observe-only macro experiment, versioned protocol, automatic episode/cohort capture, immutable labels and Learning Lab report. See [design and operations](../docs/macro-value-experiment.md) and `tests/test_macro_experiment.py`.

Completion here means the software and policy are implemented. It does not mean macro effectiveness is established or production influence is approved. Usable prospective collection is constrained by the current opportunity-coverage gap tracked in 0557.
