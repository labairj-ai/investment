# Enforce Forward and Component-Complete CC Version Transitions

- **ID:** 0726
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0720, 0724, 0725

## Problem

Version inequality permits backward or malformed releases and unrelated component bumps. Protected metadata can drift without behavioral authorization.

## Implementation guardrails and acceptance

- [x] Use canonical numeric component parsers; required bump must move forward without lexical ordering or silent normalization.
- [x] Engine hash change requires forward model version; simulator hash change requires forward simulator contract version; both require both.
- [x] Simulator version alone cannot satisfy simulator contract bump; unrelated component cannot satisfy another required bump.
- [x] Reject protected behavioral metadata changes when corresponding behavior is unchanged; no gratuitous version churn.
- [x] Policy and cadence versions drive exact manifest authorization and require corresponding simulator contract change with a forward contract bump.
- [x] Findings distinguish wrong component, missing bump, backward, malformed, and unjustified metadata drift; name prior/proposed values.
- [x] Test every canonical historical version format, backward/malformed variants, policy/cadence changes, and multi-component success.
- [x] No automatic version mutation or behavioral/economic changes. Run focused/full suites and release gate.

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
