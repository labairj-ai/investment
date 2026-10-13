# Enforce TODO Folder/Status Consistency in CI

- **ID:** 0727
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** normal
- **Depends:** 0722, 0723

## Problem

TODO folder/status consistency is tested but not an explicit mandatory workflow gate.

## Implementation guardrails and acceptance

- [ ] Add python scripts/check_todo_status.py after checkout/dependency setup, without continue-on-error.
- [ ] Retain test_real_repo_passes and all existing checker tests.
- [ ] Clean repo passes; done-folder backlog/in-progress and open-folder done reject with exit 1.
- [ ] Ignore non-TODO Markdown. Never auto-rewrite TODOs in CI or broaden checker into acceptance verification.
- [ ] Run direct checker, existing 15 tests, temporary mismatch regression, full suite and GitHub Actions.

## Completion

Pending full QA and actual GitHub Actions verification.
