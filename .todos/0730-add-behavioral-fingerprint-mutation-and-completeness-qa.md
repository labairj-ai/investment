# Add Behavioral Fingerprint Mutation and Completeness QA

- **ID:** 0730
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0729

## Problem

Static registries need executable contribution, completeness, composition and nonbehavioral stability evidence.

## Implementation guardrails and acceptance

- [ ] For every registered model/simulator function and constant, mutation by canonical name changes the expected fingerprint; restoring it restores the fingerprint.
- [ ] At minimum cover all 0729 required functions, OPEN_CHAIN_POLICY, every simulator behavioral config key and irrelevant config controls.
- [ ] Maintain explicit independent expected inventories and nonbehavioral classifications; new guarded-module functions require deliberate classification.
- [ ] Unknown/unclassified additions, removal of known protected entries, duplicate names and invalid/missing identifiers must fail.
- [ ] No tracked-file mutation, source-line-number dependence, flaky textual-only evidence, network, broker or production DB dependency.
- [ ] Use deterministic AST source providers or temporary modules/worktrees; no skips, xfails or fingerprint-security waivers.
- [ ] Prove comments/docs/dashboard/TODO and explicitly nonbehavioral helpers remain stable.
- [ ] Prove model/simulator mutations trigger release rejection without applicable forward bumps/exact manifests; correct single/multi-surface transitions pass.
- [ ] Prove a candidate-baseline rewrite cannot hide mutation.
- [ ] Repeat focused suite for determinism under GITHUB_ACTIONS=true; run existing release security/adversarial, full JUnit suite, release inventory, TODO and contract gates.
- [ ] Verify real GitHub Actions green and record model/simulator protected component counts.

## Completion

Implementation complete. Full local QA complete; real GitHub Actions verification pending.

Full suite: 2,440 passed / 16 skipped / 0 failed; exact release inventory and TODO status gates passed.

Focused fingerprint suite: 284 passed under GITHUB_ACTIONS=true. Protected inventory: model 85 functions / 4 types / 28 constants / 16 config keys; simulator 78 functions / 4 types / 16 constants / 28 config keys.

Exact trusted-prior migration check passed against fc1d475ef43998cf80c4d24b8ef6f093268f7037. Recommendation source, runtime versions, production data and release waivers are unchanged.
