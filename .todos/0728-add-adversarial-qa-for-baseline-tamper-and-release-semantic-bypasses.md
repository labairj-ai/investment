# Add Adversarial QA for Baseline Tamper and Release-Semantic Bypasses

- **ID:** 0728
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0724, 0725, 0726, 0727

## Problem

The supplied description ends after invalid open-chain policy values. This task derives its remaining scope explicitly from the bypass acceptance requirements in 0724–0726.

## Implementation guardrails and acceptance

- [ ] Prove matching direct/regenerated candidate baseline cannot hide behavioral drift or wrong/missing version bumps.
- [ ] Prove unknown categories, false/malformed reset declarations, invalid booleans and open-chain policies reject.
- [ ] Prove every protected prior/proposed field is bound, stale prior SHA rejects, and A→B authorization cannot authorize B→C.
- [ ] Prove backward/malformed/wrong-component/partial multi-component bumps and unchanged-behavior version churn reject.
- [ ] Use tmp_path-only baseline and repository fixtures; retain real CLI exit-code coverage and positive approved-transition controls.
- [ ] Run under real CI flags without global CI flag removal, skipped/xfail adversarial tests, production writes or new waivers.
- [ ] Run focused/full suites, exact release inventory, TODO gate and CC contract gate; record final CI counts.

## Completion

Pending full QA and actual GitHub Actions verification.
