# Restore GitHub Actions and Require Tests to Pass on Every Push

- **ID:** 0110
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

The GitHub Actions page for `labairj-ai/investment` shows only one workflow run (on commit `f6fbbb0`) and no runs for any subsequent commits, including the large 0094-0102 batch on `127d685`. The `.github/workflows/test.yml` file exists and looks syntactically correct (triggers on push and PR to main), but pushes are not producing workflow runs. This means the 149-test suite that's supposed to catch regressions in DB migrations, trade execution, and financial calculations has not been running. The Tests check is also not configured as a required status check for merges into main.

## Proposed approach

- Diagnose why Actions aren't running: check if the workflow was committed on the branch where Actions is enabled, whether there's a billing/quota issue on the repo, whether the workflow file has a YAML syntax problem that GitHub rejects silently, or whether Actions is disabled at the repo or org level.
- Common causes to rule out: workflow file encoding issue, indentation error in YAML, `on:` key conflict, Actions disabled in Settings → Actions → General.
- Once runs are appearing: in the repo Settings → Branches → Branch protection rules for `main`, enable "Require status checks to pass before merging" and add the Tests job as a required check.
- Consider adding a badge to `README.md` showing current CI status.
- If the Python version matrix in the workflow needs updating (currently targets 3.12; project uses 3.9+ locally), reconcile to avoid false failures.

## Touches

- `.github/workflows/test.yml` — any fixes needed
- `README.md` — CI status badge (optional)
- GitHub repo settings (branch protection rules — done in the UI, not in code)

## Done when

- [ ] A push to `main` produces a visible GitHub Actions run within 5 minutes.
- [ ] The 149-test suite runs to completion on that push and shows green.
- [ ] The most recent commit on `main` (`127d685` or later) has a passing Actions run visible in the Actions tab.
- [ ] Branch protection for `main` requires the Tests status check to pass before a PR can be merged.
- [ ] README includes a CI badge that reflects the current test status (green/red).
- [ ] A deliberate test failure on a branch PR blocks the merge (manual verification).
