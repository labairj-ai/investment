---
manifest_id: 20261022-cc-json-missing-metrics
date: 2026-10-22
category: BEHAVIORAL_MODEL_CHANGE
author: Codex
related_commit_or_pr: codex/operational-acceptance-0795
prior_fingerprint_version: cc-behavior-v1
prior_model_version: cc-v3.3
prior_simulator_version: cc-virtual-1
prior_simulator_contract_version: simulator-contract-2
prior_simulator_contract_hash: b8be3b06388cb68c7be9e53488ca6f473cc3bee15f81ed93461c802e951ce8f2
prior_engine_hash: bfdf6e9d15d452d82426975483d009b57d17827d5da9866883da1e67bd4d0193
prior_policy_version: shared-live-management-asof-1
prior_cadence_comparability_policy_version: cadence-v1
proposed_fingerprint_version: cc-behavior-v1
proposed_model_version: cc-v3.4
proposed_simulator_version: cc-virtual-1
proposed_simulator_contract_version: simulator-contract-2
proposed_simulator_contract_hash: b8be3b06388cb68c7be9e53488ca6f473cc3bee15f81ed93461c802e951ce8f2
proposed_engine_hash: 5f9fc49b8b13f7cce7672d94358c07ed188218597d9da9d9b807585176facd9f
proposed_policy_version: shared-live-management-asof-1
proposed_cadence_comparability_policy_version: cadence-v1
cohort_reset_required: true
open_chain_policy: VERSION_CENSORED
operator_acknowledged: false
---

# Pending acknowledgment: covered-call JSON missing metrics

This proposal is outside cc_change_manifests and grants no release authorization.

Before: NaN/Infinity in recommendation payloads could fail strict JSON persistence.
After: nested non-finite float payload values become null; invalid utility values
become null; invalid macro dependency values are omitted. Finite financial values,
contract selection, scoring thresholds and observe-only policy remain unchanged.

This is a model behavior transition because recommendation availability and evidence
representation change. Both helpers belong in the guarded model inventory. The
simulator hash is unchanged. Advance cc-v3.3 to cc-v3.4, reset prospective promotion
eligibility, and retain VERSION_CENSORED for existing chains. Do not combine cohorts.

Human acknowledgment and independent financial review remain outstanding. No baseline
has been promoted and no production state, model version or policy has been changed.
