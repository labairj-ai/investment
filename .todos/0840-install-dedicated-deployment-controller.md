# TODO 0840 — Install Dedicated Deployment Controller

- **ID:** 0840
- **Status:** superseded
- **Priority:** critical
- **Risk:** L5
- **Parent:** 0830
- **Depends:** 0835, 0838
- **Blocks:** 0842

## Objective

Install the fixed Deployment Agent controller separately from the writable application checkout.

## Provision

- [ ] Dedicated controller directory.
- [ ] Dedicated service identity.
- [ ] Read-only GitHub access.
- [ ] External owner bindings.
- [ ] Explicit ChatGPT connector allowlist.
- [ ] Local API credential with private filesystem permissions.
- [ ] Observation signing key.
- [ ] Private raw receipt directory.
- [ ] Sanitized observation export directory.
- [ ] Fixed systemctl permission for `investment.service`.
- [ ] Deployment poller service/timer.
- [ ] Delayed observer service/timer.

## Forbidden authority

Controller must not:

- push;
- merge;
- approve;
- edit rulesets;
- receive arbitrary shell commands;
- mutate investment state;
- invoke broker actions;
- restore the financial DB during code rollback.

## Installation acceptance

Verify actual service identity cannot:

- [ ] push Git;
- [ ] modify protected source authority;
- [ ] invoke arbitrary systemctl targets;
- [ ] read unrelated private credentials.

## Done when

Controller is installed but no qualifying production pilot has yet been claimed.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.


## Superseded

Superseded by TODO 0850 under the simplified solo-owner workflow. Internal safety controls remain, but owner-facing operation is reduced to Go / No-Go. Preserve this file as historical design context.
