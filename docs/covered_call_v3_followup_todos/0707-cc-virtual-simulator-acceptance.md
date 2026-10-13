# Validate Covered Call Virtual Simulator Against Actual Champion Behavior

- **ID:** 0707
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0704, 0705

## Problem

A virtual challenger book is only useful for promotion if its simulated execution and management process is credible.

Before using virtual V3 outcomes as evidence, the same simulator should be evaluated against completed actual V2 covered-call chains to measure how closely it reproduces:

- entry fill economics;
- management actions;
- roll timing;
- roll contract selection;
- terminal state;
- chain P&L.

## Proposed approach

Create a simulator-validation harness.

For actual V2 CC decisions with complete reconciled chains:

1. Reconstruct a virtual champion using only decision-time information.
2. Step forward through the same historical timestamps without using future information.
3. Run the deterministic management policy.
4. Compare virtual vs actual outcomes.

Measure:

### Entry execution
- modeled fill vs actual fill
- absolute fill error
- spread-position error
- fee error

### Management policy
- action agreement rate
- HOLD vs intervention confusion matrix
- first-intervention date difference
- roll-type agreement

### Contract selection
- strike difference
- expiry difference
- net roll credit/debit difference

### Economics
- total option P&L difference
- incremental-alpha difference
- execution-cost difference
- management-cost difference where measured

Persist validation runs with model/config/git provenance.

## Guardrails

- Historical replay must still enforce strict as-of data boundaries.
- Never use final actual action to seed the virtual decision.
- Actual management may include discretionary human actions; classify disagreements rather than forcing simulator to match them.
- Do not tune thresholds repeatedly on the same validation sample without versioning.
- Any calibration/tuning creates a new simulator version and requires a fresh out-of-sample validation set.
- Promotion may use a simulator version only after its validation gate passes.

## Suggested initial validation policy

Keep thresholds configurable/versioned. Suggested starting gates:

- minimum validation N: 20 completed actual chains
- entry-fill MAE <= 20% of quoted spread
- management action agreement >= 80% on policy-triggered decisions
- median first-intervention timing error <= 1 market session
- roll-type agreement >= 75% where both intervene
- median chain incremental-alpha error <= max($0.25/share, 20% of absolute actual alpha)
- zero lookahead violations
- zero actual/virtual state contamination

If current N is below threshold, status remains `INSUFFICIENT_EVIDENCE`.

## Acceptance tests

### Replay integrity
- [ ] Simulator cannot access bars/options after evaluation timestamp.
- [ ] Actual action field is unavailable to simulator policy function.
- [ ] Same replay input produces identical virtual chain.
- [ ] Changing simulator version changes validation provenance.

### Agreement metrics
- [ ] Perfect synthetic mirror produces 100% agreement.
- [ ] One-day-late roll is measured as +1 session timing error.
- [ ] Different roll type is counted as disagreement.
- [ ] NO_ACTION/HOLD distinction is normalized according to documented mapping.
- [ ] Actual discretionary action can be tagged `HUMAN_OVERRIDE` and analyzed separately.

### Execution metrics
- [ ] Fill MAE calculation is unit-correct.
- [ ] Zero-width spread is handled explicitly.
- [ ] Fees are not double counted.
- [ ] Multi-leg roll fill error is measured per leg and net.

### Validation gate
- [ ] Fails if any lookahead violation is detected.
- [ ] Fails below required sample size.
- [ ] Fails if action agreement below threshold.
- [ ] Fails if economic-error threshold exceeded.
- [ ] Passing creates immutable simulator-certification record.
- [ ] 0706 rejects evidence from uncertified simulator version.

## QA requirements

### Backend QA
- [ ] Run validation against all currently completed actual CC chains with usable evidence.
- [ ] Report total N and exclusion reasons.
- [ ] Separate automatic-policy-aligned actual actions from human overrides.
- [ ] Confirm no actual execution tables are modified.

### Review QA
- [ ] Manually inspect at least 10 divergent simulator/actual cases.
- [ ] Categorize divergence: data timing, policy mismatch, discretionary human action, quote quality, execution-model error, or bug.
- [ ] Document whether simulator bias is conservative or optimistic.

### Regression QA
- [ ] Existing V2 live management behavior is unchanged.
- [ ] Existing V3 observer decisions are unchanged.
- [ ] Validation harness has no broker-write capability.
