# TODO 0850 — Install Deployment Controller and Complete Three Successful Supervised Releases

- **ID:** 0850
- **Status:** backlog
- **Priority:** critical strategic
- **Risk:** L5
- **Depends:** 0849
- **Blocks:** future low-risk automatic PR activation
- **Supersedes:** 0840, 0842 and 0844

## Objective

Install and prove the Deployment Controller, then complete three successful supervised releases without adding owner ceremony.

## Controller authority

Controller may only verify the exact approved release, back up state, checkout exact merge SHA, restart the fixed service, run fixed health/canary checks, compare protected state, create receipts and perform code rollback when required.

It must not push, merge, approve, alter governance, execute arbitrary commands, mutate investment data or invoke broker/execution functions.

## First production pilot

Use the real PR from 0849. After owner Go:

- [ ] exact reviewed head merges;
- [ ] merged-main CI passes;
- [ ] internal deployment authorization is created;
- [ ] controller admission passes;
- [ ] backup succeeds;
- [ ] exact merge SHA deploys;
- [ ] fixed service restarts;
- [ ] dashboards and Development Agent API pass;
- [ ] Advisor canary passes;
- [ ] holdings and investment state remain unchanged;
- [ ] delayed health observation passes;
- [ ] durable deployment receipt is preserved.

No second owner approval.

## Failure acceptance

Prove fail-closed behavior for wrong SHA, stale approval, failed merged-main CI, dirty checkout, failed backup, failed restart, failed HTTP health, failed Advisor canary, protected-state mutation and interrupted deployment.

## Three-success evidence

Complete at least three genuine supervised releases. Track Go/No-Go decisions, CI/Reviewer/deployment failures, rollbacks, authority violations and investment-state mutations.

Do not delay merely to manufacture category diversity.

## Readiness decision

Produce LOW-RISK AUTO-PR: READY or LOW-RISK AUTO-PR: NOT READY — reason.

This concerns automatic creation of low-risk PRs only. It never authorizes autonomous merge or deployment.

## Future operating mode

If the owner later says Go, the agent may automatically discover, plan, build, review, validate and open eligible low-risk PRs. Owner Go remains required before anything reaches main.

## Guardrails

No autonomous merge, deployment, L3+, financial logic, governance changes or investment-state mutation. Keep kill switch and human Go before merge.

## Done when

The system has demonstrated reliable supervised operation and the only remaining decision is whether to allow automatic creation of low-risk PRs.
