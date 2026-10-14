---
manifest_id: 20261013-0729-named-fingerprint-definition
date: 2026-10-13
category: EVIDENCE_INFRASTRUCTURE
author: Codex implementing user-requested 0729
related_commit_or_pr: 0729, 0730, 0731
fingerprint_migration: legacy-to-named-v1
prior_cadence_comparability_policy_version: cadence-v1
prior_engine_hash: 7e6a8a4cbc5ee2d5ca5b824e9d94be8addad49c9de52d364a8eb3a3727281b6d
prior_fingerprint_version: cc-behavior-v0
prior_model_version: cc-v3.2
prior_policy_version: shared-live-management-asof-1
prior_simulator_contract_hash: 9ac625ac79d8ecf860b5994778337ae5f4628e515d09cae2c1444ccd64970e39
prior_simulator_contract_version: simulator-contract-1
prior_simulator_version: cc-virtual-1
proposed_cadence_comparability_policy_version: cadence-v1
proposed_engine_hash: fccf8fce066e0dc582b5838fa001c63a8e73cfcb3237677fe6264668dd0216bb
proposed_fingerprint_version: cc-behavior-v1
proposed_model_version: cc-v3.2
proposed_policy_version: shared-live-management-asof-1
proposed_simulator_contract_hash: 36094c7261e2f31307ca43635cc29ce23e5b6ea55dd5be85e2ccae586118c13f
proposed_simulator_contract_version: simulator-contract-1
proposed_simulator_version: cc-virtual-1
cohort_reset_required: true
open_chain_policy: VERSION_CENSORED
operator_acknowledged: true
---

# Named behavioral fingerprint definition migration

Trusted prior Git source: fc1d475ef43998cf80c4d24b8ef6f093268f7037. The user requested an intentional authorized transition for expanded fingerprint coverage, with no automatic model/simulator bumps.

Runtime/economic source, protected constants, behavioral config and all existing model/simulator/policy versions remain unchanged. The checker must prove this from the exact prior Git source; a matching candidate/manifest cannot override failed proof.

Only the legacy fingerprint definition is migrated to named AST components. Existing evidence retains its recorded identity; expanded identities may censor old virtual contracts per the existing policy. No production database migration or write is performed.

The release manifest remains exact-state bound. Subsequent behavioral mutations require the existing applicable forward component versions and exact behavioral manifest. This migration cannot be reused for another definition or runtime-version change.
