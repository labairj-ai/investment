# Restore CC Adversarial Release QA Under Real CI Environment

- **ID:** 0723
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0718, 0721

## Problem

Four adversarial tests generate fixtures through the production --update-baseline CLI, which correctly rejects writes in CI. This is a test setup defect; retain the fail-closed guard.

## Implementation guardrails and acceptance

- [x] Generate valid fixtures using current_contract_state / write_baseline only under tmp_path; never write the real baseline.
- [x] Keep subprocess assertions for missing/malformed/unknown-schema baseline exit 1 and unchanged contract exit 0.
- [x] Prove both GITHUB_ACTIONS=true and CI=true reject --update-baseline with exit 1.
- [x] Do not unset CI flags globally, weaken _in_ci, skip/xfail tests, or add release waivers.
- [x] Run adversarial suite, full pytest tests/ -v --tb=short --junitxml=test-results.xml, release inventory and CC checker.
- [x] Verify real GitHub Actions reaches and passes CC contract step; record final counts.

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
