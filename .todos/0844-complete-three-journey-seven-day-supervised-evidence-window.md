# TODO 0844 — Complete Three-Journey / Seven-Day Supervised Evidence Window

- **ID:** 0844
- **Status:** superseded
- **Priority:** critical strategic
- **Risk:** L5
- **Parent:** 0831
- **Depends:** 0837–0843
- **Blocks:** final bounded-autonomy activation decision

## Objective

Produce genuine prospective evidence sufficient for an owner promotion decision.

## Required journeys

At least three distinct successful journeys across at least seven America/New_York calendar days.

Preferred diversity:

- Journey A: L0 documentation/static cleanup.
- Journey B: L1 test/tooling improvement.
- Journey C: L2 passive CSS/UI improvement.

Each must include:

- system-derived or explicit owner signal;
- automatic discovery;
- isolated build;
- independent review;
- live oracle PASS;
- exact-head CI;
- ChatGPT review;
- owner OK;
- owner merge;
- Deployment Agent release;
- signed HEALTHY observation;
- post-fix recurrence measurement;
- `defect_recurrence_checked=true`;
- `defect_recurred=false`.

## Promotion requirements

At conclusion verify:

- [ ] 0825–0830 complete.
- [ ] Three unique qualifying releases.
- [ ] Seven calendar days.
- [ ] Current harness matches.
- [ ] Technical cert current.
- [ ] Oracle cert current.
- [ ] Deployment Agent cert current.
- [ ] GitHub protection current.
- [ ] Snapshot current.
- [ ] Scheduler healthy.
- [ ] No unresolved pause.
- [ ] No abnormal deployment.
- [ ] No repeated failure condition.
- [ ] No financial-state mutation.
- [ ] Owner-promotion verifier available.

## Output

Generate `GO_FOR_OWNER_STAGE_REVIEW` or `NO-GO` with exact blockers.

Even GO must not automatically modify configuration.

## Final guardrail

Do not enable `autonomous_implementation=true` in this task.

The first future activation should be a separate L5 owner-reviewed change moving only to the next bounded stage.

## Done when

0831 has real prospective evidence and the owner receives a defensible GO/NO-GO decision.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.


## Superseded

Superseded by TODO 0850 under the simplified solo-owner workflow. Internal safety controls remain, but owner-facing operation is reduced to Go / No-Go. Preserve this file as historical design context.
