# Enforce CC Manifest Semantic Values and Complete Transition Identity

- **ID:** 0725
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0719, 0720, 0724

## Problem

Populated manifest strings currently qualify without semantic validation, and policy/cadence identities are omitted from transition matching.

## Implementation guardrails and acceptance

- [x] Allow only NON_BEHAVIORAL, EVIDENCE_INFRASTRUCTURE, BEHAVIORAL_MODEL_CHANGE.
- [x] Parse actual booleans; reject unknown spellings, require operator acknowledgment and behavioral cohort_reset_required=true.
- [x] Validate open_chain_policy against the 0712 VERSION_CENSORED policy; unknown/missing policy cannot authorize simulator change.
- [x] Bind prior/proposed model, simulator, simulator contract versions, engine/simulator hashes, policy and cadence policy versions.
- [x] Template contains every machine-required field; templates never authorize transitions.
- [x] Duplicate IDs and duplicate exact applicable transitions remain failures. Invalid semantic findings name field and expected values.
- [x] Use table-driven invalid-value and complete identity tests. Migration is deterministic: old incomplete manifests remain readable but cannot authorize a new full-identity transition.
- [x] No economics changes. Run parser, focused/adversarial, full suite and release gate.

## Completion

Completed 2026-10-13. Implementation: 5da9016; final follow-up corrects the version_bumped summary to require all component-forward transitions.

- Local focused suites: 126 passed, 0 skipped, 0 failed.
- Adversarial suite alone under GITHUB_ACTIONS=true: 24 passed, 0 failed.
- Local full suite: 2079 passed, 16 skipped, 0 failed.
- GitHub Actions: 2077 passed, 18 skipped, 0 failed; all release gates executed successfully.
- CI evidence: https://github.com/labairj-ai/investment/actions/runs/38485375047
- CI trusted prior: c4bbd36187bec0efeb8ff56434d174bccdaaab19.
- PR and push event fixtures both executed in real CI, including real temporary Git histories and subprocess A→B approval/B→C replay rejection. The workflow itself was triggered by a push to main.
- TODO mismatch fixture exited 1; corrected temporary fixture exited 0.
- Release failure inventory and committed CC baseline are unchanged; no new waiver.
- Production baseline-update guard remains fail-closed for both CI flags. V3 remains observe-only; no economics or DB changes.
