# TODO 0841 — Execute First Real Supervised Improvement Journey

- **ID:** 0841
- **Status:** superseded
- **Priority:** critical
- **Risk:** L3
- **Parent:** 0829
- **Depends:** 0837, 0838, 0839
- **Blocks:** 0842, 0844

## Objective

Prove one genuine end-to-end Development Agent software change.

## Candidate

Prefer L0 documentation or L1 bounded tooling/test improvement.

Avoid financial, governance, authentication and deployment code.

## Activation change

Use a separate reviewed owner-approved PR to set only the minimum supervised configuration required.

Continue `autonomous_implementation=false` and `auto_merge=false`.

## Required flow

`DISCOVERED` → `PLANNED` → `APPROVED_FOR_BUILD` → `BUILDING` → `REVIEWING` → `VALIDATING` → `PR_READY` → `AWAITING_OWNER`.

Then:

- ChatGPT reviews actual PR;
- owner says OK/NO;
- exact-head owner attestation;
- owner merge only after OK.

## Required evidence

- [ ] actual signal;
- [ ] frozen plan;
- [ ] deterministic L0/L1 risk;
- [ ] isolated Builder;
- [ ] distinct Reviewer;
- [ ] live oracle PASS;
- [ ] trusted validation;
- [ ] exact-head CI;
- [ ] owner decision;
- [ ] merge SHA.

## Done when

0829 can close for the first real supervised journey.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.


## Superseded

Superseded by TODO 0849 under the simplified solo-owner workflow. Internal safety controls remain, but owner-facing operation is reduced to Go / No-Go. Preserve this file as historical design context.
