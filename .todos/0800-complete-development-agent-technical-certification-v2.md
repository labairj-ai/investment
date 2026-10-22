# Complete Development-Agent Technical Certification v2

- **ID:** 0800
- **Status:** backlog
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** 0796, 0797, 0798, 0799, 0792, 0803, 0804

## Problem

The coding-agent architecture is implemented, but technical certification remains partial because several real environmental components have not yet passed.

A complete technical certificate is required before real supervised pilots begin.

## Scope and acceptance

- [ ] Run `harness-canary-2` against the exact current harness SHA.
- [ ] Require real PASS for:
  - workspace isolation
  - reviewer independence
  - evidence binding
  - production mutation denial
  - financial change detection
  - human gate
  - audit lineage
  - PR handoff
  - OS validation sandbox
  - effective GitHub protection
  - authentic production snapshot
- [ ] Run `authority-adversarial-2`.
- [ ] Require every adversarial component to PASS.
- [ ] Bind certification to:
  - current harness hash
  - configuration hash
  - contract/principle hash
  - sandbox image digest
  - GitHub policy evidence
  - snapshot provenance
  - exact code SHA
- [ ] Persist the certificate immutably.
- [ ] Display certificate as current on the Development Agent dashboard.
- [ ] Do not count technical certification as a supervised pilot.

## QA requirements

- [ ] No mandatory component is `PARTIAL`, `UNAVAILABLE`, `NOT_RUN` or missing.
- [ ] Adversarial suite PASS.
- [ ] Full repository CI PASS.
- [ ] Production state unchanged.
- [ ] Dashboard accurately reports `READY_FOR_SUPERVISED`.

## Implementation guardrails

- Technical certification grants no merge/deployment authority.
- Technical certification alone does not enable autonomy.

## Source

User-supplied 2026-10-22 development-agent operational acceptance phase. Requirements and dependencies preserved; backlog creation does not authorize implementation or activation.

## Additional trust-boundary gates — 2026-10-22

0803 and 0804 must PASS before technical certification. Candidate-controlled tests and unconstrained CI execution cannot supply certification evidence.
