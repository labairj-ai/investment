# Separate System Acceptance from Dimension Eligibility

- **ID:** 0539
- **Status:** in-progress
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0536, 0537, 0538

## Problem

The v1.4 acceptance gate blocks the entire scorer when any one of the 32 ticker-dimension cells has a score range above one, even though the downstream model already supports stable, borderline, and unstable per-dimension eligibility. This makes the system-level acceptance rule conflict with the dimension-level usability model and hides useful diagnostic information.

## Proposed approach

- Preserve the blocked v1.4 artifact as audit evidence.
- Analyze its 32 cells by range, standard deviation, mode concentration, entropy, and score sequence shape before changing policy.
- Define system-level acceptance around complete N=20 observations, valid response contracts, anchor/regime/synthetic health, contract stability, and reconciled production ledger accounting.
- Persist every ticker-dimension stability classification; allow only policy-eligible dimensions to become usable while unstable dimensions remain excluded.
- Version the changed policy as validation config v1.5 with an amendment explaining the semantic change; do not silently loosen v1.4 thresholds.

## Touches

- `scripts/validate_macro_scorer.py`
- `validation_config.json`
- `portfolio_ai.py` acceptance eligibility
- Acceptance and diagnostic tests
- Blocked artifact `out/macro_validation_340befe6-cedb-4e95-add0-3711eb3cb30f.json` on optiplex

## Done when

- [ ] The blocked v1.4 artifact has a 32-cell diagnostic distribution recorded.
- [ ] System acceptance and per-dimension eligibility are explicitly defined and tested.
- [ ] Complete N=20 data is required, while unstable dimensions remain unusable without blocking stable dimensions.
- [ ] Config v1.5 documents the policy change and preserves v1.4 history.
- [ ] A completed production scoring ledger exists before the next formal acceptance.
- [ ] The next 0535 run verifies atomic activation, 32 rows, current hashes, and eligible dimensions only.

## Progress — 2026-09-20

Implemented v1.5 system-versus-dimension gate semantics and added the repeatability diagnostic script. Remaining work is operational: complete a reconciled production scoring cycle, record the blocked v1.4 32-cell distribution, and rerun formal acceptance under v1.5.
