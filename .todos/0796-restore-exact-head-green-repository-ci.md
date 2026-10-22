# Restore Exact-Head Green Repository CI

- **ID:** 0796
- **Status:** backlog
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** 0795

## Problem

Development-agent requirements 0785 and 0792 require the repository test suite and existing release gates to pass on the exact candidate SHA.

Current deployment evidence is not sufficient while exact-head CI is red.

## Scope and acceptance

- [ ] Rebase/update the development-agent hardening branch on current `main`.
- [ ] Resolve any merge conflicts without weakening agent governance or investment safeguards.
- [ ] Run locally:
  - TODO consistency
  - coding-agent contract
  - development-agent governance
  - focused agent tests
  - full repository test suite
  - release baseline
  - CC behavioral contract
- [ ] Push exact candidate SHA.
- [ ] Require GitHub Actions to complete on that same SHA.
- [ ] Capture workflow URL, commit SHA and complete test inventory.
- [ ] Require zero unexpected failures.
- [ ] Preserve existing skipped-test inventory unless explicitly reviewed.
- [ ] Update development-agent evidence receipts to point only to the green exact-head run.

## QA requirements

- [ ] GitHub Actions conclusion = `success`.
- [ ] Workflow head SHA == candidate SHA.
- [ ] Full suite reports zero failures.
- [ ] CC behavioral contract passes.
- [ ] Agent governance checks pass.
- [ ] No stale CI run from an earlier commit is accepted.

## Implementation guardrails

- Do not use `continue-on-error` or baseline manipulation to hide new failures.
- Green exact-head CI is mandatory evidence, not advisory evidence.

## Source

User-supplied 2026-10-22 development-agent operational acceptance phase. Requirements and dependencies preserved; backlog creation does not authorize implementation or activation.
