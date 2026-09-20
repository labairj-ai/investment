# Version Stability Boundaries and Acceptance Health States

- **ID:** 0546
- **Status:** backlog
- **Created:** 2026-09-20
- **Priority:** normal
- **Depends:** 0543, 0544, 0545

## Problem

The stable and borderline standard-deviation cutoffs are still hard-coded in Python, while the validation configuration is supposed to be the executable policy. Operational health also reports ACCEPTED when the stored acceptance contract is stale and unusable.

## Proposed approach

- Add `stable_stddev_max` and `borderline_stddev_max` to validation config and consume them in the canonical dimension policy.
- Bump the policy to v1.7 and include the boundaries in the contract/config provenance.
- Report `ACCEPTED_CURRENT`, `ACCEPTANCE_STALE_CONTRACT`, or `PRE_ACCEPTANCE` consistently in health output.
- Add tests for configured boundary changes and stale acceptance health.

## Touches

- `validation_config.json`
- `portfolio_ai.py` stability and health reporting
- Validation and health tests

## Done when

- [ ] Stability boundaries are loaded from versioned config, not hard-coded.
- [ ] v1.7 records the policy change and preserves v1.6 history.
- [ ] Stale acceptance cannot appear as current ACCEPTED health.
- [ ] Config-boundary and health-state tests pass.
