# Run Formal N=20 Macro Scorer Acceptance

- **ID:** 0535
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0529, 0530, 0531, 0532, 0533, 0534, 0536, 0537, 0538, 0539, 0540, 0541, 0542, 0543, 0544, 0545, 0546

## Problem

The current acceptance record was generated against a validator that does not run the production scoring contract (see 0529) and with thresholds that are not fully enforced from config (see 0530). Running the formal N=20 acceptance before those issues are resolved would spend significant compute re-validating the wrong contract and produce an artifact that still doesn't answer the question: "Is the production scoring system with production evidence stable?" This item is the capstone — the acceptance run that closes the validation architecture once 0529–0534 are complete.

## Proposed approach

- Run `validate_macro_scorer.py` with `--live`, no `--n-repeats` override, no `--smoke`.
- After completion, verify the artifact fields: `run_type=acceptance`, `N=20`, `verdict=PASS`, `activated=true`, plus `config_hash`, `scorer_contract_hash`, model identity, and commit SHA all present.
- In SQLite, verify:
  - Exactly one active acceptance pointer in `macro_acceptance_state`
  - Exactly 32 rows in `macro_dimension_validation` (8 tickers × 4 dimensions)
  - All 32 rows share the same `acceptance_id`, `config_hash`, `model_identity`, and `scorer_contract_hash`
  - No rows were inserted or patched manually after the run completed
- Document the verified artifact path and DB state as the new accepted baseline.

## Touches

- No code changes expected — this is an operational run and verification step
- `validate_macro_scorer.py` (invoked, not modified)
- SQLite DB on optiplex (read-only verification queries)
- Acceptance artifact JSON (read-only verification)

## Done when

- [ ] Acceptance run completes with `run_type=acceptance`, `N=20`, `verdict=PASS`, `activated=true`
- [ ] Artifact contains `config_hash`, `scorer_contract_hash`, model identity, and commit SHA
- [ ] SQLite shows exactly one active acceptance pointer
- [ ] SQLite shows exactly 32 validation rows for 8 tickers × 4 dimensions
- [ ] All 32 rows share identical acceptance/config/model/scorer hashes
- [ ] No manual DB patching was performed after the run

## Review — 2026-09-20

Pending operational acceptance. Keep open until 0529–0534 meet their completion criteria and the formal N=20 production-contract run and database verification are documented. This TODO review did not launch a live acceptance run.

## Follow-up review — 2026-09-20

The v1.4 N=20 run completed with `verdict=BLOCK` and `activated=false`. The blocked artifact is preserved as evidence. It showed repeatability failures in several dimensions and a missing completed production ledger, so the next run must wait for 0536–0539, a completed production scoring cycle, and the versioned acceptance-policy decision.
