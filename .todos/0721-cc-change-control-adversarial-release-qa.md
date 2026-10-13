# Add Adversarial Release QA for CC V3 Change Control

- **ID:** 0721
- **Status:** backlog
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0718, 0719, 0720

## Problem

Change-control infrastructure protects the prospective experiment. Happy-path tests are insufficient; common bypass patterns must be proven ineffective.

## Proposed approach

Add a focused adversarial suite covering the complete chain:

`committed baseline -> current source/config -> declared category -> applicable manifest -> required version bumps -> evidence reset semantics`

Cover:

- missing/malformed/stale baseline
- behavioral drift without bump
- wrong-component bump
- no manifest
- unrelated old manifest
- duplicate applicable manifests
- false NON_BEHAVIORAL/EVIDENCE_INFRASTRUCTURE declaration
- simulator change without open-chain impact declaration
- manually edited baseline
- manually bumped version with stale manifest
- tampered manifest hashes

At least some tests must invoke `scripts/check_cc_contract.py` as a subprocess and assert the real exit code.

## Implementation guardrails

- No production DB writes.
- Use temporary repos/config fixtures/worktrees.
- Do not mock away behavioral hashes.
- A bypass test passes only when the invalid release is rejected.
- Tests must be deterministic and offline.
- No broker/network dependency.
- Preserve enough integration coverage to test the actual CI path.

## Touches

- `tests/test_cc_change_control.py` or equivalent
- `scripts/check_cc_contract.py`
- test fixtures/helpers
- GitHub Actions if separate focused step is useful
- release docs

## Acceptance tests

### Baseline attacks

- [ ] Missing baseline => exit 1 in CI mode.
- [ ] Malformed baseline => exit 1.
- [ ] Unknown schema/version => exit 1.
- [ ] Unauthorized baseline manipulation is detected by the integrity/transition policy.

### Version bypasses

- [ ] Engine hash change + no bump => reject.
- [ ] Engine hash change + unrelated model bump only => reject.
- [ ] Utility model change + unrelated simulator bump only => reject.
- [ ] Multi-component change + partial bumps => reject.

### Manifest bypasses

- [ ] No manifest => reject behavioral change.
- [ ] Old manifest => reject.
- [ ] Manifest for different hashes => reject.
- [ ] Duplicate applicable manifests => reject.
- [ ] Missing operator acknowledgment => reject.
- [ ] Template only => reject.

### Classification bypasses

- [ ] Behavioral drift declared NON_BEHAVIORAL => reject.
- [ ] Decision-changing code declared EVIDENCE_INFRASTRUCTURE => reject.
- [ ] True dashboard-only NON_BEHAVIORAL change => pass.

### End-to-end success

- [ ] Approved behavioral transition with exact manifest and correct bumps => exit 0.
- [ ] Approved non-behavioral unchanged contract => exit 0.
- [ ] CLI and direct Python API return consistent outcomes.

## QA requirements

- [ ] Each rejection asserts non-zero result and specific failure message/code.
- [ ] No test relies only on broad exception matching.
- [ ] Fixtures restore automatically.
- [ ] Parallel tests cannot contaminate one another.
- [ ] Adversarial suite runs on PRs to `main`.
- [ ] Contract failure visibly blocks workflow.
- [ ] Run focused suite on Optiplex after deployment and record passing count.

## Done when

- [ ] Known bypass patterns are explicitly tested
- [ ] Invalid behavioral releases reliably fail
- [ ] Valid controlled transitions pass
- [ ] The actual CI path is covered
