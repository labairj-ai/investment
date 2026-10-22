---
manifest_id: 20261022-cc-finite-decision-inputs
date: 2026-10-22
category: BEHAVIORAL_MODEL_CHANGE
author: Codex
related_commit_or_pr: codex/trust-boundary-0803-0809
prior_fingerprint_version: cc-behavior-v1
prior_model_version: cc-v3.4
prior_simulator_version: cc-virtual-1
prior_simulator_contract_version: simulator-contract-2
prior_simulator_contract_hash: b8be3b06388cb68c7be9e53488ca6f473cc3bee15f81ed93461c802e951ce8f2
prior_engine_hash: 5f9fc49b8b13f7cce7672d94358c07ed188218597d9da9d9b807585176facd9f
prior_policy_version: shared-live-management-asof-1
prior_cadence_comparability_policy_version: cadence-v1
proposed_fingerprint_version: cc-behavior-v1
proposed_model_version: cc-v3.5
proposed_simulator_version: cc-virtual-1
proposed_simulator_contract_version: simulator-contract-2
proposed_simulator_contract_hash: b8be3b06388cb68c7be9e53488ca6f473cc3bee15f81ed93461c802e951ce8f2
proposed_engine_hash: e7fcc056ad509fbcedca4cae7efaff1a848bdbed7030b8667a687f1ad46e0f5c
proposed_policy_version: shared-live-management-asof-1
proposed_cadence_comparability_policy_version: cadence-v1
cohort_reset_required: true
open_chain_policy: VERSION_CENSORED
operator_acknowledged: false
---

# Decision input validity before recommendation math

Before: missing/non-finite required inputs could reach formatting, score rounding,
financial summary math, challenger selection or management calculations before JSON
serialization. JSON null conversion did not establish decision validity.

After: missing, non-finite, non-numeric and out-of-range required inputs produce an
explicit INSUFFICIENT_DATA finding and no recommendation, before those calculations.
There is no zero substitution. Derived non-finite arithmetic also fails closed. Holding/spot metrics, candidate metrics, required
challenger coverage and management position metrics are checked at their boundaries.
Optional evidence still permits null; NumPy numeric scalars and Pandas absence values
are JSON safe. Finite recommendations are compared directly against immutable
deployed cc-v3.4 source on identical fixtures and remain unchanged.

Model version advances cc-v3.4 to cc-v3.5. Simulator, selection/scoring thresholds,
observe-only policy and execution permissions are unchanged. Reset prospective
promotion eligibility; retain VERSION_CENSORED for existing chains. No cohorts are
combined. No database, promotion or deployment is performed by this change.

This proposal is outside the active manifest directory until human acknowledgment.
Independent financial review remains required before merge.
