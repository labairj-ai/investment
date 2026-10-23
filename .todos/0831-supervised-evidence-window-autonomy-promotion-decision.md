# TODO 0831 — Complete Supervised Evidence Window and Prepare Autonomy Promotion Decision

- **ID:** 0831
- **Status:** backlog
- **Priority:** high strategic
- **Risk:** L5 — autonomy promotion
- **Depends:** 0825, 0826, 0827, 0828, 0829, 0830
- **Blocks:** bounded autonomy activation

## Problem

A single successful agent journey is insufficient evidence for autonomous implementation.

The repository already requires:

- at least three supervised successes;
- at least seven calendar days of prospective evidence.

This TODO collects that evidence and produces a promotion recommendation. It does **not** enable autonomy.

## Required evidence window

Complete at least three distinct real improvement journeys over at least seven calendar days.

Recommended diversity:

### Journey A

- L0 documentation / metadata / cleanup.

### Journey B

- L1 test/tooling improvement.

### Journey C

- L2 passive UI/site enhancement.

Each journey must include:

- production-derived or explicit owner signal;
- automatic discovery;
- bounded plan;
- isolated Builder;
- independent Reviewer;
- trusted oracle validation;
- exact-head CI;
- owner OK/NO;
- owner merge;
- Deployment Agent release;
- signed post-deployment healthy observation.

## Success criteria

For each journey:

- [ ] no authority violation;
- [ ] no financial-state mutation;
- [ ] no rollback required for successful qualification;
- [ ] no unresolved HIGH/CRITICAL Reviewer finding;
- [ ] exact-head owner approval;
- [ ] exact merge/deployment SHA linkage;
- [ ] healthy post-deploy observation;
- [ ] no recurrence of the fixed defect during observation window.

## Software-agent metrics

Track:

- candidate count;
- candidate acceptance rate;
- duplicate/suppression rate;
- time signal → plan;
- time plan → PR;
- Builder correction iterations;
- Reviewer rejection rate;
- focused-test pass rate;
- first-pass full CI rate;
- owner approval rate;
- owner rejection rate;
- deployment success rate;
- rollback rate;
- defect recurrence rate;
- runtime incidents after deployment.

Do **not** use portfolio performance or investment P&L to evaluate software-agent quality.

## Readiness requirements

Before recommending autonomy:

- [ ] 0825–0830 complete;
- [ ] three qualifying supervised successes;
- [ ] seven-day minimum observation period satisfied;
- [ ] current technical certificate PASS;
- [ ] current oracle certificate PASS;
- [ ] current deployment-agent certificate PASS;
- [ ] current GitHub protection evidence PASS;
- [ ] no active emergency stop;
- [ ] no unresolved autonomy pause;
- [ ] no repeated-failure condition;
- [ ] no abnormal deployment observation;
- [ ] current harness matches evidence harness;
- [ ] all exact-head CI evidence green.

## Promotion output

Generate an owner-reviewable promotion report containing:

- qualifying run IDs;
- dates;
- risk levels;
- PRs;
- merge SHAs;
- deployed SHAs;
- deployment receipts;
- post-deploy observations;
- metrics;
- failures/non-qualifying attempts;
- current harness hash;
- current safety configuration;
- recommended stage.

## Explicit prohibition

This TODO must **not** itself change:

`autonomous_implementation`

from false to true.

Autonomy activation requires a separate L5 owner-reviewed PR after this evidence is complete.

## Recommended promotion target

If evidence is clean, recommend:

- `autonomy_stage = SHADOW → BUILD_ONLY` first;
- then observed BUILD_ONLY acceptance;
- then `PR` stage;
- only then consider:
  `autonomous_implementation=true`

with:

- maximum risk L2;
- initial daily cap 1;
- hard maximum 3;
- owner merge required;
- owner deployment authorization required;
- no autonomous financial changes;
- no autonomous L3–L5 changes.

## Done when

- [ ] Required prospective evidence exists.
- [ ] Promotion report is generated.
- [ ] Owner receives a clear GO/NO-GO recommendation.
- [ ] Autonomy remains disabled until a separate explicit owner decision.
