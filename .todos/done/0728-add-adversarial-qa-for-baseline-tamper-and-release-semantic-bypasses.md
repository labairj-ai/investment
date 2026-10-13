# Add Adversarial QA for Baseline Tamper and Release-Semantic Bypasses

- **ID:** 0728
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0724, 0725, 0726, 0727

## Problem

The supplied description ends after invalid open-chain policy values. This task derives its remaining scope explicitly from the bypass acceptance requirements in 0724–0726.

## Implementation guardrails and acceptance

- [x] Prove matching direct/regenerated candidate baseline cannot hide behavioral drift or wrong/missing version bumps.
- [x] Prove unknown categories, false/malformed reset declarations, invalid booleans and open-chain policies reject.
- [x] Prove every protected prior/proposed field is bound, stale prior SHA rejects, and A→B authorization cannot authorize B→C.
- [x] Prove backward/malformed/wrong-component/partial multi-component bumps and unchanged-behavior version churn reject.
- [x] Use tmp_path-only baseline and repository fixtures; retain real CLI exit-code coverage and positive approved-transition controls.
- [x] Run under real CI flags without global CI flag removal, skipped/xfail adversarial tests, production writes or new waivers.
- [x] Run focused/full suites, exact release inventory, TODO gate and CC contract gate; record final CI counts.

## Completion

Completed 2026-10-13. Implementation: 5da9016; final follow-up corrects the version_bumped summary to require all component-forward transitions.

- Local focused suites: 126 passed, 0 skipped, 0 failed.
- Adversarial suite alone under GITHUB_ACTIONS=true: 24 passed, 0 failed.
- Local full suite: 2079 passed, 16 skipped, 0 failed.
- GitHub Actions: 2077 passed, 18 skipped, 0 failed; all release gates executed successfully.
- CI evidence: https://github.com/labairj-ai/investment/actions/runs/38485375047
- CI trusted prior: c4bbd36187bec0efeb8ff56434d174bccdaaab19.
- PR and push event fixtures both executed in real CI, including real temporary Git histories and subprocess A→B approval/B→C replay rejection. The workflow itself was triggered by a push to main.
- TODO mismatch fixture exited 1; corrected temporary fixture exited 0.
- Release failure inventory and committed CC baseline are unchanged; no new waiver.
- Production baseline-update guard remains fail-closed for both CI flags. V3 remains observe-only; no economics or DB changes.
