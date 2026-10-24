# TODO 0842 — Execute First Deployment Agent Production Pilot

- **ID:** 0842
- **Status:** superseded
- **Priority:** critical
- **Risk:** L5
- **Parent:** 0830
- **Depends:** 0840, 0841
- **Blocks:** 0844

## Objective

Deploy the 0841 low-risk release entirely through the installed Deployment Agent.

## Required flow

- [ ] exact-head owner review;
- [ ] owner merge;
- [ ] merged-main CI PASS;
- [ ] separate owner deployment authorization;
- [ ] poller discovers authorization;
- [ ] admission verifies owner/head/merge/main/CI;
- [ ] preflight PASS;
- [ ] rollback backup;
- [ ] protected-state identity captured;
- [ ] exact merge SHA checkout;
- [ ] service restart;
- [ ] dashboards PASS;
- [ ] authenticated API PASS;
- [ ] unauthorized API 403;
- [ ] Advisor canaries PASS;
- [ ] investment state unchanged;
- [ ] holdings unchanged;
- [ ] valid `deployment-evidence-1`;
- [ ] delayed signed observation HEALTHY;
- [ ] candidate closes only after cross-bound evidence succeeds.

## Failure matrix

Stage before production pilot:

- [ ] stale authorization;
- [ ] wrong SHA;
- [ ] dirty tree;
- [ ] backup failure;
- [ ] restart failure;
- [ ] HTTP failure;
- [ ] canary failure;
- [ ] protected-state mutation;
- [ ] interrupted transaction.

No failure may produce `DEPLOYED_VERIFIED`.

## Done when

0830 can close.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.


## Superseded

Superseded by TODO 0850 under the simplified solo-owner workflow. Internal safety controls remain, but owner-facing operation is reduced to Go / No-Go. Preserve this file as historical design context.
