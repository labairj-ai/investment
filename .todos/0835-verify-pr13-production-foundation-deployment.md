# TODO 0835 — Verify PR #13 Production Foundation Deployment

- **ID:** 0835
- **Status:** in-progress
- **Priority:** critical
- **Risk:** L5 — production deployment
- **Depends:** PR #13 merged
- **Blocks:** 0836–0842

## Objective

Complete and preserve production verification for PR #13 merge:
`d12dcf3746dc7266ef4de02f06a48c2b629580e6`.

The GitHub release gates and owner deployment authorization already exist. This task establishes whether the exact code foundation is actually running on OptiPlex.

## Required acceptance

- [ ] OptiPlex repository HEAD exactly equals `d12dcf3746dc7266ef4de02f06a48c2b629580e6`.
- [ ] Tracked worktree clean.
- [ ] `investment.service` active.
- [ ] Investment dashboard HTTP 200.
- [ ] Development Agent dashboard HTTP 200.
- [ ] Authenticated Development Agent API HTTP 200.
- [ ] Unauthorized Development Agent API HTTP 403.
- [ ] Advisor functional canary PASS.
- [ ] Advisor mutation-safety canary PASS.
- [ ] Holdings unchanged.
- [ ] Investment database state unchanged.
- [ ] Development ledger unchanged except explicitly expected release evidence.
- [ ] Rollback backup exists and passes integrity verification.
- [ ] Activation remains `autonomous_implementation=false`, `supervised_loop_enabled=false`, `supervised_publish_pr=false`, `auto_merge=false`, `autonomy_stage=SHADOW`.
- [ ] Preserve sanitized deployment receipt.
- [ ] Record exact merge CI run.
- [ ] Record exact deployment authorization comment ID.
- [ ] Close PR #12 as superseded if still open.

## Guardrails

Deployment of PR #13 is not operational certification of the oracle, Scout, supervised loop or Deployment Agent.

Do not install/activate 0826–0831 runtime components in this task.

## Done when

A durable `DEPLOYED_VERIFIED` foundation receipt exists for `d12dcf37...`.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.
