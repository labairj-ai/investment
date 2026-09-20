# Make Drift Provenance Contract and Input Aware

- **ID:** 0538
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0537

## Problem

Drift detection currently compares scores when `evidence_hash` is unchanged, but it ignores `scorer_contract_hash` and the exact `prompt_hash`. Measured betas are part of the prompt but are not represented in the current evidence hash, so valid contract or input changes can be misreported as unexplained drift. Zero `rate_interaction` values are also classified as negative instead of neutral.

## Proposed approach

- Compare scorer contract and prompt hashes before classifying score changes.
- Classify differences as `contract_changed`, `input_changed`, or genuine `unexplained_drift`; only the last counts against the drift gate.
- Include all prompt inputs, including measured betas, in the relevant provenance hash.
- Make positive values positive, negative values negative, and exact zero or malformed values excluded from interaction groups.

## Touches

- `scripts/validate_macro_scorer.py`
- `scripts/macro_attribution.py`
- `portfolio_ai.py` score provenance and drift tests

## Done when

- [ ] Contract changes never count as unexplained drift.
- [ ] Prompt/input changes never count as unexplained drift.
- [ ] Same contract and prompt with changed scores is classified as unexplained drift.
- [ ] Zero interaction is neutral and excluded from positive/negative cohorts.
- [ ] Tests cover all classifications and zero handling.

## Completion — 2026-09-20

Implemented in `03636aa`: drift compares contract, prompt, and evidence provenance; contract/input changes are reported separately, and zero interaction is neutral.
