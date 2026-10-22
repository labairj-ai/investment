# Resolve Existing Covered-Call CI and Behavioral-Contract Failures

- **ID:** 0795
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** none

## Problem

The development-agent hardening branch currently reproduces seven existing covered-call failures. The repository-wide full suite therefore remains red, and the covered-call engine behavioral fingerprint differs from the expected contract.

Development-agent certification must not normalize or ignore unrelated failing repository gates.

## Scope and acceptance

- [ ] Reproduce all seven covered-call failures from clean `main`.
- [ ] Record exact failing test names, failure messages and affected source files.
- [ ] Compare current covered-call engine fingerprint against the expected behavioral-contract fingerprint.
- [ ] Determine for each failure whether it represents:
  - genuine regression
  - stale behavioral baseline
  - intentional behavior change
  - invalid/non-deterministic test
  - environment/data dependency
- [ ] Do not change the CC baseline until the semantic difference is understood.
- [ ] If behavior is wrong, fix implementation and add regression coverage.
- [ ] If behavior is intentionally correct, produce a reviewed behavioral-contract migration with explicit before/after rationale.
- [ ] Preserve existing covered-call risk, recommendation and promotion safeguards.
- [ ] Re-run focused covered-call tests after every fix.
- [ ] Require zero unexplained covered-call failures before closure.

## QA requirements

- [ ] Previously failing seven cases pass or have an explicitly reviewed replacement contract.
- [ ] `scripts/check_cc_contract.py` passes.
- [ ] No weakening/deletion/skipping of existing CC tests solely to obtain green CI.
- [ ] Covered-call production behavior remains observe-only where currently governed that way.
- [ ] Full suite is executed after focused fixes.

## Implementation guardrails

- Do not treat these failures as acceptable technical debt for agent certification.
- Do not automatically adopt the observed engine hash as the new expected hash.
- Do not change CC scoring/promotion thresholds unless separately justified and reviewed.

## Source

User-supplied 2026-10-22 development-agent operational acceptance phase. Requirements and dependencies preserved; backlog creation does not authorize implementation or activation.

## Implementation checkpoint — 2026-10-22

Clean main `6cb6fde` reproduces 7 failures (327 passing focused cases). See
[the evidence and pending contract migration](../docs/evidence/operational-acceptance-20261022/README.md).
Both JSON helpers are now classified as protected model behavior. Nine strict JSON
regression cases pass. The baseline and runtime model version remain unchanged
pending human acknowledgment and independent review. This TODO remains open.
