# Add Behavioral Fingerprint Mutation and Completeness QA

- **ID:** 0730
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0729

## Problem

Static registries need executable contribution, completeness, composition and nonbehavioral stability evidence.

## Implementation guardrails and acceptance

- [x] For every registered model/simulator function and constant, mutation by canonical name changes the expected fingerprint; restoring it restores the fingerprint.
- [x] At minimum cover all 0729 required functions, OPEN_CHAIN_POLICY, every simulator behavioral config key and irrelevant config controls.
- [x] Maintain explicit independent expected inventories and nonbehavioral classifications; new guarded-module functions require deliberate classification.
- [x] Unknown/unclassified additions, removal of known protected entries, duplicate names and invalid/missing identifiers must fail.
- [x] No tracked-file mutation, source-line-number dependence, flaky textual-only evidence, network, broker or production DB dependency.
- [x] Use deterministic AST source providers or temporary modules/worktrees; no skips, xfails or fingerprint-security waivers.
- [x] Prove comments/docs/dashboard/TODO and explicitly nonbehavioral helpers remain stable.
- [x] Prove model/simulator mutations trigger release rejection without applicable forward bumps/exact manifests; correct single/multi-surface transitions pass.
- [x] Prove a candidate-baseline rewrite cannot hide mutation.
- [x] Repeat focused suite for determinism under GITHUB_ACTIONS=true; run existing release security/adversarial, full JUnit suite, release inventory, TODO and contract gates.
- [x] Verify real GitHub Actions green and record model/simulator protected component counts.

## Completion

Implementation complete. Local and real GitHub Actions QA complete.

Full suite: 2,440 passed / 16 skipped / 0 failed; exact release inventory and TODO status gates passed.

Focused fingerprint suite: 284 passed under GITHUB_ACTIONS=true. Protected inventory: model 85 functions / 4 types / 28 constants / 16 config keys; simulator 78 functions / 4 types / 16 constants / 28 config keys.

Exact trusted-prior migration check passed against fc1d475ef43998cf80c4d24b8ef6f093268f7037. Recommendation source, runtime versions, production data and release waivers are unchanged.


CI: [passing implementation run](https://github.com/labairj-ai/investment/actions/runs/38491829391) on 9d320bd: **2,438 passed / 18 skipped / 0 failed**. TODO status, exact release inventory and CC contract-check steps all executed and passed. No new waiver.

Prior engine: `7e6a8a4cbc5ee2d5ca5b824e9d94be8addad49c9de52d364a8eb3a3727281b6d`; prior simulator: `9ac625ac79d8ecf860b5994778337ae5f4628e515d09cae2c1444ccd64970e39`.

Proposed engine: `fccf8fce066e0dc582b5838fa001c63a8e73cfcb3237677fe6264668dd0216bb`; proposed simulator: `36094c7261e2f31307ca43635cc29ce23e5b6ea55dd5be85e2ccae586118c13f`. Local macOS/Python 3.9 and CI Linux/Python 3.12 hashes agree.
