# Restore CC Adversarial Release QA Under Real CI Environment

- **ID:** 0723
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0718, 0721

## Problem

Four adversarial tests generate fixtures through the production --update-baseline CLI, which correctly rejects writes in CI. This is a test setup defect; retain the fail-closed guard.

## Implementation guardrails and acceptance

- [ ] Generate valid fixtures using current_contract_state / write_baseline only under tmp_path; never write the real baseline.
- [ ] Keep subprocess assertions for missing/malformed/unknown-schema baseline exit 1 and unchanged contract exit 0.
- [ ] Prove both GITHUB_ACTIONS=true and CI=true reject --update-baseline with exit 1.
- [ ] Do not unset CI flags globally, weaken _in_ci, skip/xfail tests, or add release waivers.
- [ ] Run adversarial suite, full pytest tests/ -v --tb=short --junitxml=test-results.xml, release inventory and CC checker.
- [ ] Verify real GitHub Actions reaches and passes CC contract step; record final counts.

## Completion

Pending full QA and actual GitHub Actions verification.
