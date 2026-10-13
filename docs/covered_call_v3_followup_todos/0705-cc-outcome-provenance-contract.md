# Define Covered Call Outcome Provenance Contract

- **ID:** 0705
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0704

## Problem

The Covered Call Learning Lab and promotion evaluator now combine several types of evidence:

- actual executed trades;
- market-path-only counterfactual labels;
- modeled virtual challenger chains;
- estimated expiry economics.

Without a strict provenance contract, simulated outcomes can accidentally be displayed, aggregated, or promoted as if they were actual realized performance.

The system needs a typed distinction between observed, virtual, reconstructed, and estimated evidence.

## Proposed approach

Introduce an explicit `outcome_source` contract for every CC outcome/label/economic record.

Minimum enum:

- `ACTUAL_EXECUTION`
- `PROSPECTIVE_VIRTUAL`
- `MARKET_PATH_ONLY`
- `ESTIMATED_COUNTERFACTUAL`

Optional subfields:

- `execution_source`
- `management_source`
- `price_path_source`
- `cost_source`
- `assignment_source`

Each outcome should also include:

- source timestamp range
- model/config version where modeled
- whether broker-reconciled
- whether market-data coverage verified
- whether complete or censored
- units
- chain identifier
- originating decision episode
- source evidence hash

## Semantics

### ACTUAL_EXECUTION
Broker/manual execution records reconciled to an actual recommendation and trade chain.

### PROSPECTIVE_VIRTUAL
A virtual position created prospectively at decision time and managed forward without lookahead.

### MARKET_PATH_ONLY
Observed underlying/option path labels with no assumed management execution.

### ESTIMATED_COUNTERFACTUAL
Retrospective or formula-derived estimate that was not run prospectively and must never count as promotion evidence.

## Guardrails

- Promotion logic must never treat `ESTIMATED_COUNTERFACTUAL` as prospective evidence.
- Dashboard realized-P&L metrics must use only `ACTUAL_EXECUTION`.
- Virtual challenger performance must always be labeled as virtual.
- Market-path-only labels may calibrate touch probabilities but may not be used as realized roll-chain economics.
- Do not infer missing provenance from table location; provenance must be persisted explicitly.
- Source enum is append-only/versioned.
- Actual evidence must never be downgraded to virtual/estimated.
- Virtual evidence must never be upgraded to actual.

## Touches

- `covered_call_ledger.py`
- virtual book structures from 0704
- CC API/report payload
- Learning Lab dashboard
- promotion evaluator
- tests

## Acceptance tests

### Source typing
- [ ] Actual broker-reconciled chain => `ACTUAL_EXECUTION`.
- [ ] Virtual challenger lifecycle => `PROSPECTIVE_VIRTUAL`.
- [ ] Underlying OHLC touch label without chain => `MARKET_PATH_ONLY`.
- [ ] Formula-only hypothetical expiry P&L => `ESTIMATED_COUNTERFACTUAL`.

### Invalid combinations
- [ ] Virtual outcome cannot set `broker_reconciled=true`.
- [ ] Market-path-only outcome cannot contain realized execution cost.
- [ ] Estimated counterfactual cannot set `prospective=true`.
- [ ] Actual outcome requires actual/reconciled execution identifiers.
- [ ] Promotion evaluator rejects unknown provenance enum values.

### Aggregation
- [ ] Realized P&L report excludes virtual and estimated rows.
- [ ] Challenger report includes virtual rows but labels them separately.
- [ ] Calibration for strike touch may use `MARKET_PATH_ONLY` when path coverage is complete.
- [ ] Roll-frequency calibration requires actual or prospective-virtual management source.
- [ ] Assignment-policy violations used for promotion require actual or prospective-virtual complete chains.

### Immutability
- [ ] Once persisted, outcome provenance cannot be updated in place.
- [ ] A corrected outcome is appended as a new revision with provenance preserved.

## QA requirements

### Backend QA
- [ ] Existing CC labels are migrated/classified without rewriting decision-time evidence.
- [ ] Existing actual trades receive `ACTUAL_EXECUTION`.
- [ ] Existing pure path labels receive `MARKET_PATH_ONLY`.
- [ ] No legacy row is silently assumed actual if evidence is incomplete.

### Dashboard QA
- [ ] Every performance panel visibly distinguishes Actual vs Virtual.
- [ ] Tooltips/details expose outcome source.
- [ ] No aggregate labeled "realized" includes virtual data.
- [ ] Low-N and censored counts remain visible.

### Regression QA
- [ ] Existing CC reports load with legacy rows.
- [ ] Existing promotion state remains V2.
- [ ] No production recommendation behavior changes in this TODO.
