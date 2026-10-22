# Expand Development-Agent Adversarial Certification for Evidence and Authority Bypasses

- **ID:** 0792
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0785, 0786, 0787, 0788, 0789, 0790, 0791

## Problem

The existing adversarial suite covers important isolation and governance failures, but the next certification revision must explicitly attack the newly identified evidence, supervision, snapshot and GitHub identity boundaries.

## Scope and acceptance

- [ ] Add adversarial cases for:
  - forged validation PASS records
  - stale validation receipts
  - mixed-candidate validation evidence
  - arbitrary SQLite DB presented as production snapshot
  - forged snapshot provenance
  - stale production backup
  - synthetic actor/supervision claims
  - replayed supervised run
  - autonomous invocation while autonomy disabled
  - supervised/autonomous mode confusion
  - stale remote PR head
  - remote/local SHA mismatch
  - GitHub ruleset bypass
  - incomplete protection visibility
  - stale certification after harness changes
- [ ] Version the canary contract to a new revision.
- [ ] Require every mandatory component to PASS.
- [ ] `PARTIAL`, `UNAVAILABLE`, `NOT_RUN` and missing components cannot satisfy operational certification.
- [ ] Bind adversarial certification to the exact harness/config/contracts hash.
- [ ] Ensure failures produce explainable blocker records.
- [ ] Keep all certification tests free of production mutations.

## QA requirements

- [ ] Each adversarial mutation must independently cause certification failure.
- [ ] Positive controls must demonstrate legitimate flows still PASS.
- [ ] Full repository test suite passes.
- [ ] Real GitHub CI passes for the exact candidate SHA.
- [ ] Production snapshot test uses authenticated isolated backup provenance.
- [ ] Test counts and evidence receipts are machine-verifiable.

## Implementation guardrails

- Do not mock away the security boundary being tested.
- Replay providers may test model behavior but cannot certify operational containment.
- Real production state remains immutable.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.
