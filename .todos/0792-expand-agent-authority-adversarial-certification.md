# Expand Development-Agent Adversarial Certification for Evidence and Authority Bypasses

- **ID:** 0792
- **Status:** in-progress
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

## Implementation progress — 2026-10-22

Implementation: `dev_agent/adversarial.py; dev_agent/certification.py; tests/test_development_agent_hardening.py`. Versioned harness-canary-2 and authority-adversarial-2 cover forged/stale/mixed receipts, snapshot/provenance/freshness, synthetic/replayed supervision, mode/disable gates, remote SHA, rulesets and stale certification. Fixture success cannot grant operational PASS.

See [hardening plan](../docs/plans/development-agent-hardening-0785-0794.md),
[operator contract](../docs/development-agent.md) and
[prospective pilot protocol](../docs/development-agent-pilots.md).

Focused, adversarial and browser results are recorded in the PR evidence.
Acceptance remains open pending exact-head CI, unchanged release/CC gates and
applicable operational evidence. Current main reproduces seven CC contract/test
failures. Docker is unavailable on this development machine; GitHub main has no
classic protection or active rules. No live pilot, production backup authenticity,
physical-device acceptance or autonomy activation is claimed. No TODO is moved to
done based solely on fixture success.
