# Formalize Covered Call Release Baseline Failure Inventory

- **ID:** 0710
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** normal
- **Depends:** none

## Problem

The covered-call V3 deployment passed its release checks, while the broader suite still contains four failures that reproduce on the unchanged baseline.

Calling them "pre-existing" is acceptable for one deployment, but leaving permanent known failures undocumented creates regression risk: a new real failure can become indistinguishable from old background noise.

The repository needs an explicit baseline-failure contract.

## Proposed approach

Create a machine-readable and human-readable inventory for every currently accepted baseline failure.

For each failure record:

- test node ID
- full failure signature
- first known failing commit if determinable
- baseline commit used to reproduce
- affected subsystem
- owner/category
- reason believed pre-existing
- whether accepted debt or active bug
- linked TODO/issue
- expected resolution
- whether permitted in CI/release gating
- expiry/review date for any temporary waiver

Add a release-check helper that compares current failures with the approved baseline inventory.

Release behavior:

- exact known approved failure => report as known debt
- known test with changed failure signature => fail
- any new failure => fail
- expected known failure disappears => report improvement and require inventory cleanup
- expired waiver => fail until reviewed

## Guardrails

- Never use broad `xfail` or ignore patterns that can hide unrelated failures.
- Match exact test IDs and normalized failure signatures where practical.
- Every accepted failure must have a linked remediation/decision record.
- Waivers should be time-bounded when feasible.
- This TODO does not excuse covered-call-specific failures.

## Acceptance tests

- [ ] Four known baseline failures are recognized exactly.
- [ ] A fifth new failure causes release gate failure.
- [ ] Changed assertion/error for a known test causes failure.
- [ ] Resolved known failure is reported as stale inventory.
- [ ] Expired waiver causes failure.
- [ ] Inventory parser rejects duplicate test IDs.
- [ ] Inventory parser rejects entries without owner/reason/link.

## QA requirements

### CI QA
- [ ] Run against unchanged known baseline and confirm only approved failures are classified as known.
- [ ] Inject one synthetic additional failure and confirm gate fails.
- [ ] Alter one known failure signature and confirm gate fails.
- [ ] Remove one known failure and confirm stale-inventory warning appears.

### Documentation QA
- [ ] Each of the four failures has a remediation decision.
- [ ] Covered Call V3 release notes reference exact baseline state.
- [ ] No blanket "ignore failures" path exists.
