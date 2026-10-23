---
manifest_id: 20261023-snapshot-lineage-normalization
date: 2026-10-23
category: BEHAVIORAL_MODEL_CHANGE
author: repository owner (explicit acknowledgment), Codex (implementation)
related_commit_or_pr: https://github.com/labairj-ai/investment/pull/10
prior_fingerprint_version: cc-behavior-v1
prior_model_version: cc-v3.4
prior_simulator_version: cc-virtual-1
prior_simulator_contract_version: simulator-contract-2
prior_simulator_contract_hash: b8be3b06388cb68c7be9e53488ca6f473cc3bee15f81ed93461c802e951ce8f2
prior_engine_hash: 5f9fc49b8b13f7cce7672d94358c07ed188218597d9da9d9b807585176facd9f
prior_policy_version: shared-live-management-asof-1
prior_cadence_comparability_policy_version: cadence-v1
proposed_fingerprint_version: cc-behavior-v1
proposed_model_version: cc-v3.4
proposed_simulator_version: cc-virtual-1
proposed_simulator_contract_version: simulator-contract-3
proposed_simulator_contract_hash: 7f5b57c1502c8eae2b4b6170ee9d287334c8b22ac1c1e2355e713b06a6affcd9
proposed_engine_hash: 5f9fc49b8b13f7cce7672d94358c07ed188218597d9da9d9b807585176facd9f
proposed_policy_version: shared-live-management-asof-1
proposed_cadence_comparability_policy_version: cadence-v1
cohort_reset_required: true
open_chain_policy: VERSION_CENSORED
operator_acknowledged: true
---

# Approved snapshot-lineage simulator contract migration

Owner explicitly approved this exact transition in the deployment conversation. Existing main bb4c9a8 normalizes non-finite snapshot evidence to null before lineage digest; finite inputs and recommendation arithmetic are unchanged. Keep cc-v3.4, cc-virtual-1 and the engine hash unchanged.

Advance simulator-contract-2 to simulator-contract-3 and the reviewed corresponding baseline. The explicit prospective_cohort_version=simulator-contract-3 configuration identity changes config_digest and resets prospective eligibility; old decisions fail CONFIG_MISMATCH and old simulator certificates no longer match. The existing censor_version_mismatch path closes old open chains as VERSION_CENSORED during normal evaluation; never combine contract-2 and contract-3 evidence. No production database is modified by this source migration. Observe-only, risk, promotion and execution safeguards remain unchanged.

New prospective observation begins only after deployment; no historical evidence is relabeled or backdated.
