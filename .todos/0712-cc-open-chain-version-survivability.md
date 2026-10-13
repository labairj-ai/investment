# Define Open Virtual CC Chain Version-Survivability Policy

- **ID:** 0712
- **Status:** backlog
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0711

## Problem

When simulator-relevant code changes while a prospective virtual covered-call chain is still open, the engine can reject further evaluation with a contract-mismatch error. Without an explicit lifecycle policy this strands open chains, silently reduces usable evidence N, and makes promotion-cohort sizes unpredictable.

## Proposed approach

Default policy: do not migrate active experimental chains across simulator contracts.

- Add terminal/censor state `VERSION_CENSORED`.
- When an open chain's frozen simulator contract no longer matches the current runnable contract: close it as `VERSION_CENSORED`; preserve all evidence accumulated before censoring; exclude from paired promotion comparisons; never continue under the new rules or retrofit with the new simulator.
- Persist with the censor record: original and current contract hashes, mismatch-detected timestamp, last-successfully-evaluated timestamp, `promotion_eligible=false`, `censor_source=SIMULATOR_CONTRACT_CHANGE`.
- Virtual-management job detects mismatch before policy evaluation and appends exactly one censor transition; subsequent scheduler runs are idempotent.
- Add dashboard metrics: open chains by simulator contract, version-censored chain count, % of prospective opportunities lost to version changes, evidence N by simulator contract version.

## Touches

- `covered_call_virtual.py` (censor transition logic)
- `covered_call_validation.py` or equivalent management scheduler
- DB schema (censor state, metadata columns)
- Learning Lab dashboard (version-censored N, open-chain contract column, promotion exclusion reason)
- Tests

## Done when

- [ ] Open virtual chain under contract A advances normally while current contract is A
- [ ] Changing to contract B causes exactly one `VERSION_CENSORED` transition per affected chain
- [ ] No further virtual actions or fills occur after version censoring
- [ ] Re-running scheduler does not duplicate censor records
- [ ] Prior actions and fills remain immutable and queryable
- [ ] Promotion evaluator excludes version-censored chains and surfaces the exclusion reason
- [ ] Dashboard shows version-censored N separately from other exclusion reasons
- [ ] New virtual decisions opened after contract B start under B; A and B chains remain distinguishable
