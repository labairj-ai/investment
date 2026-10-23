# Approved simulator contract reconciliation

Current main 3b497914270fe53beaecba9c8d2fdd0b80f427fe already contains bb4c9a8: snapshot_inputs in covered_call_evidence.create_decision_contract are passed through covered_call_ledger.clean before the market-lineage digest. This enables a snapshot with non-finite evidence to receive a strict-JSON/null lineage rather than raising before contract persistence. Finite values and recommendation arithmetic are unchanged. This function is guarded by the simulator fingerprint, so the existing simulator-contract-2 baseline no longer matches main.

Proposed deliberate transition: simulator-contract-2 → simulator-contract-3. Keep model cc-v3.4 and cc-virtual-1 unchanged; engine fingerprint is identical. Reset prospective simulator eligibility; preserve VERSION_CENSORED for existing chains and preserve every financial/risk/promotion safeguard. Do not combine incomparable cohorts. Exact hashes are in simulator-contract-proposal.json, computed using an in-memory source overlay only.

APPROVED AND APPLIED following explicit owner financial acknowledgment in the deployment conversation. The reviewed version bump, transition manifest and baseline are applied. Existing cohort isolation and VERSION_CENSORED policy are preserved. No production financial data was modified. Exact-head release validation remains required before merge or deployment.
