# Decouple CC Simulator Certification From Unrelated Repo Changes

- **ID:** 0711
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0707

## Problem

Simulator certification currently binds validity to the repository's exact current Git SHA. Any unrelated commit — dashboard copy, portfolio-advisor prompt tweak, documentation edit — invalidates an otherwise unchanged simulator certificate. This makes operating the prospective virtual covered-call book unnecessarily brittle and forces re-certification after every deploy regardless of whether CC behavior changed.

## Proposed approach

Introduce a versioned **Covered Call Simulator Contract Identity**: a deterministic hash computed from only the files and functions that can affect prospective virtual CC behavior.

- Hash inputs: `covered_call_virtual.py` (`fill_model`, `enforce_asof`, `context_for`, `evaluate_snapshot`, terminal/economics functions); live CC management functions reused by the simulator (`evaluate_cc_management_state`, `_check_assignment_eligible`, `_suggest_next_call`, `_remaining_call_alpha`, `_friction_at_expiry`); option math; execution model contract; tax/assignment functions; simulator-relevant config subset; explicit version constants.
- Persist alongside the certificate: `simulator_contract_version`, `simulator_contract_hash`, `certified_at_git_sha`, `current_git_sha`, `management_contract_hash`, `execution_contract_hash`, `config_contract_hash`.
- Certification validity requires exact match on behaviorally relevant contract hashes, not repo HEAD. `certified_at_git_sha` is kept for provenance only.
- Hash must be deterministic across machines (normalized semantic/source inputs, no timestamps or filesystem metadata).
- Changing contract-composition rules increments `simulator_contract_version`.

## Touches

- `covered_call_validation.py`
- `covered_call_virtual.py`
- `covered_call_outcomes.py` (if shared digest helpers used)
- `config/strategy.json`
- Simulator certification schema
- Learning Lab certification panel
- Tests

## Done when

- [ ] Changing only `README.md` or a dashboard label does not change the simulator contract hash
- [ ] Changing `evaluate_cc_management_state`, `_suggest_next_call`, or `fill_model` changes the contract hash
- [ ] Same source/config on two machines produces the same hash
- [ ] Existing certificate remains valid after an unrelated commit; becomes invalid after a simulator-relevant code or config change
- [ ] Current Git SHA may differ from certified Git SHA while certificate remains valid when contract hash matches
- [ ] Missing contract metadata or unknown contract version invalidates certification (fail-closed)
- [ ] Learning Lab shows contract version/hash and both Git SHAs separately
