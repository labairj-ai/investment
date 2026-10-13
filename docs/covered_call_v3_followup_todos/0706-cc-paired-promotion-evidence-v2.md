# Build Paired Covered Call Promotion Evidence V2

- **ID:** 0706
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0704, 0705, 0707

## Problem

Current `promotion_evidence()` requires complete outcomes for champion and challenger, but the observe-only challenger historically lacked a complete management/execution path.

After 0704 and 0705, promotion should compare:

- actual V2 champion outcome
- prospective virtual V3 challenger outcome

for the same decision opportunity, with strict provenance and independence rules.

## Proposed approach

Create a V2 promotion-evidence contract that evaluates matched decision episodes only.

Eligibility for a paired cohort requires:

- decision marked prospective;
- current V3 model version;
- current config hash;
- current promotion-policy version;
- certified simulator version from 0707;
- one independent opportunity per ticker/session;
- champion outcome source = `ACTUAL_EXECUTION` or champion NO_CALL;
- challenger outcome source = `PROSPECTIVE_VIRTUAL` or challenger NO_CALL;
- both outcomes complete for the comparison horizon;
- no unresolved data-quality/censoring condition;
- identical decision-time market snapshot lineage.

For NO_CALL:

- incremental CC alpha = 0 vs hold by definition;
- roll count = 0;
- management cost = 0;
- assignment violation = false;
- execution cost = 0.

For SELL_CC require complete economic fields.

Persist a promotion snapshot containing:

- exact cohort IDs
- model version
- simulator version
- config hash
- promotion-policy version
- git SHA
- N
- divergent N
- elapsed prospective duration
- alpha delta
- roll-rate delta
- management-cost delta
- execution-cost delta
- assignment-policy violations
- calibration metrics
- source/provenance composition
- exclusions by reason

## Guardrails

- Retrospective reconstructed challenger paths cannot qualify.
- Same ticker/session duplicate runs count once.
- Do not cherry-pick only successful completed virtual chains; censored/excluded counts must be reported.
- Promotion criteria must be committed before the eligible cohort matures.
- Changing model/config invalidates prior prospective evidence for the new version.
- Promotion remains an explicit transition; no automatic activation.
- Rollback remains one explicit state/config action.
- Challenger must not influence live recommendations until gate passes and explicit promotion occurs.

## Acceptance tests

### Pair eligibility
- [ ] Actual V2 + prospective virtual V3 complete => eligible pair.
- [ ] Actual V2 + market-path-only V3 => excluded.
- [ ] Actual V2 + retrospective estimated V3 => excluded.
- [ ] Champion NO_CALL + prospective virtual V3 SELL_CC => eligible when V3 chain completes.
- [ ] Actual V2 SELL_CC + V3 NO_CALL => eligible once champion completes.
- [ ] Both NO_CALL => paired but non-divergent.
- [ ] Config-hash mismatch => excluded.
- [ ] Model-version mismatch => excluded.
- [ ] Simulator-version mismatch/uncertified => excluded.
- [ ] Duplicate ticker/session => only canonical opportunity counts.

### Metrics
- [ ] Alpha improvement = paired challenger minus champion incremental alpha.
- [ ] Roll-rate delta uses the same denominator/cohort.
- [ ] Management-cost delta uses same unit basis.
- [ ] Execution-cost delta uses same unit basis.
- [ ] Assignment-policy violation count is challenger-specific and exact.
- [ ] Divergent N classification matches decision divergence enum.
- [ ] Prospective duration uses earliest and latest eligible decision dates.

### Promotion gate
- [ ] Fails below minimum N.
- [ ] Fails below minimum divergent N.
- [ ] Fails below minimum prospective days.
- [ ] Fails if alpha improvement does not beat configured threshold.
- [ ] Fails if roll-rate regression exceeds limit.
- [ ] Fails if management-cost regression exceeds limit.
- [ ] Fails on assignment-policy violations above configured maximum.
- [ ] Fails if required calibration threshold is not met.
- [ ] Passing evidence still does not switch scorer automatically.
- [ ] Explicit transition to V3 stores immutable promotion snapshot.

### Version invalidation
- [ ] Changing economic/scorer config starts a new eligibility cohort.
- [ ] Changing activation mode alone does not alter feature/scorer contract hash if intended.
- [ ] Changing V3 scorer/model version prevents old evidence from qualifying for the new model.
- [ ] Changing certified simulator version prevents silent carry-forward.

## QA requirements

### Backend QA
- [ ] Run promotion report on current production data before/after migration.
- [ ] Confirm current V3 remains ineligible.
- [ ] Confirm exclusion reasons are explainable and queryable.
- [ ] Confirm no historical virtual data is incorrectly marked prospective if generated retrospectively.

### Dashboard QA
- [ ] Promotion card shows eligible N, divergent N, prospective days, and all gate failures.
- [ ] Actual vs virtual provenance counts are visible.
- [ ] Excluded/censored pair counts are visible.
- [ ] Promotion evidence can be drilled to exact episode IDs.

### Operational QA
- [ ] Promotion command still requires explicit operator action.
- [ ] Rollback command returns to V2 cleanly.
- [ ] Promotion snapshot survives restart.
- [ ] Git/config/simulator mismatch causes fail-closed fallback to V2.
