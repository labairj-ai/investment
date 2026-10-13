# Enforce CC V3 Behavioral Contract Checks in CI

- **ID:** 0718
- **Status:** backlog
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0716, 0717

## Problem

0716 introduced `scripts/check_cc_contract.py`, but GitHub Actions does not execute it. `.cc_contract_baseline.json` is also not committed, and the checker currently treats a missing baseline as successful first-deployment state.

The model-freeze policy therefore exists in code but is not an unavoidable merge/release control.

## Proposed approach

1. Generate and review the initial `.cc_contract_baseline.json` from the exact current frozen V3 implementation.
2. Commit that baseline.
3. Add a mandatory GitHub Actions step running `python scripts/check_cc_contract.py`.
4. Make missing/malformed/unknown baseline fail closed in normal CI.
5. Preserve an explicit local bootstrap command for intentional baseline creation.
6. Ensure CI can never invoke `--update-baseline`.

## Implementation guardrails

- CI must never auto-update the baseline.
- Missing baseline in normal CI is a hard failure.
- Generate baseline from a clean reviewed `main`.
- Baseline updates require an intentional reviewed commit.
- Do not use `continue-on-error`.
- Do not route contract failures through the release-baseline waiver system.
- Unrelated repo changes must pass when behavior hashes are unchanged.
- V3 remains observe-only.
- No economic/scoring changes in this TODO.

## Touches

- `.github/workflows/test.yml`
- `.cc_contract_baseline.json`
- `scripts/check_cc_contract.py`
- `covered_call_change_control.py`
- tests

## Acceptance tests

- [ ] `--update-baseline` creates deterministic behavioral state locally.
- [ ] Repeated generation on identical source/config is equivalent.
- [ ] Baseline contains model/simulator/contract versions, engine hash, simulator contract hash, policy version, and cadence policy version.
- [ ] Workflow contains explicit non-optional CC contract-check step.
- [ ] Approved unchanged contract passes.
- [ ] Deleted baseline fails CI.
- [ ] Malformed/unknown baseline fails CI.
- [ ] CI never invokes `--update-baseline`.
- [ ] Simulator/management drift without version handling fails.
- [ ] README/dashboard-only change passes.
- [ ] Simulator-relevant config drift fails.
- [ ] Matching Git SHA cannot bypass hash mismatch.

## QA requirements

- [ ] Generate baseline from clean `main` and record source SHA.
- [ ] Run `python scripts/check_cc_contract.py`.
- [ ] Run full test suite.
- [ ] On a disposable branch, change a behavioral function and confirm CI fails.
- [ ] Revert and confirm CI passes.
- [ ] Pull baseline to Optiplex and confirm deployed tree matches.
- [ ] Confirm V3 observe-only state is unchanged.

## Done when

- [ ] Contract check is mandatory in CI
- [ ] Committed baseline exists
- [ ] Missing baseline fails closed
- [ ] Behavioral drift cannot merge without change-control handling
