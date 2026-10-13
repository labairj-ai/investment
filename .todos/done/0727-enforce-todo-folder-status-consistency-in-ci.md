# Enforce TODO Folder/Status Consistency in CI

- **ID:** 0727
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** normal
- **Depends:** 0722, 0723

## Problem

TODO folder/status consistency is tested but not an explicit mandatory workflow gate.

## Implementation guardrails and acceptance

- [x] Add python scripts/check_todo_status.py after checkout/dependency setup, without continue-on-error.
- [x] Retain test_real_repo_passes and all existing checker tests.
- [x] Clean repo passes; done-folder backlog/in-progress and open-folder done reject with exit 1.
- [x] Ignore non-TODO Markdown. Never auto-rewrite TODOs in CI or broaden checker into acceptance verification.
- [x] Run direct checker, existing 15 tests, temporary mismatch regression, full suite and GitHub Actions.

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
