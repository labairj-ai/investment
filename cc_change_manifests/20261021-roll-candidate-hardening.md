---
manifest_id: 20261021-roll-candidate-hardening
date: 2026-10-21
category: BEHAVIORAL_MODEL_CHANGE
author: Codex
related_commit_or_pr: working-tree-review-fixes
prior_cadence_comparability_policy_version: cadence-v1
prior_engine_hash: fccf8fce066e0dc582b5838fa001c63a8e73cfcb3237677fe6264668dd0216bb
prior_fingerprint_version: cc-behavior-v1
prior_model_version: cc-v3.2
prior_policy_version: shared-live-management-asof-1
prior_simulator_contract_hash: 36094c7261e2f31307ca43635cc29ce23e5b6ea55dd5be85e2ccae586118c13f
prior_simulator_contract_version: simulator-contract-1
prior_simulator_version: cc-virtual-1
proposed_fingerprint_version: cc-behavior-v1
proposed_model_version: cc-v3.3
proposed_simulator_version: cc-virtual-1
proposed_simulator_contract_version: simulator-contract-2
proposed_simulator_contract_hash: b8be3b06388cb68c7be9e53488ca6f473cc3bee15f81ed93461c802e951ce8f2
proposed_engine_hash: bfdf6e9d15d452d82426975483d009b57d17827d5da9866883da1e67bd4d0193
proposed_policy_version: shared-live-management-asof-1
proposed_cadence_comparability_policy_version: cadence-v1
cohort_reset_required: true
open_chain_policy: VERSION_CENSORED
operator_acknowledged: true
---

# Roll candidate hardening

The authorized review fixes retain the existing working-tree roll changes: ROLL_OUT
must clear both the current expiry and risk event; replacement strikes above the
split-contract ceiling are excluded; negative-alpha candidates remain ranked rather
than excluded; premium percentage uses spot as its denominator.

These changes affect replacement selection in both live management and replay.
Model cc-v3.2 advances to cc-v3.3; simulator-contract-1 advances to
simulator-contract-2. Ranking may now return a least-bad negative-alpha contract.

This transition resets prospective promotion eligibility. Existing virtual chains
follow VERSION_CENSORED policy; old cohorts must not be combined with the new
contract. No production chains or databases were modified during this local fix.
The user authorized these fixes with “fix” following the review. Deployment has
not been performed. Validation is recorded in the task result.

Approved-thesis policy readers now recognize canonical ACTIVE and legacy active states. Ambiguous active CC policies fail closed. These changes are included in this undeployed behavioral transition. Portfolio mutations and execution risk changes have separate regression coverage.
