# TODO 0843 — Implement Authenticated Owner Autonomy-Promotion Verifier

- **ID:** 0843
- **Status:** in-progress
- **Priority:** critical
- **Risk:** L5 — autonomy authority
- **Depends:** PR #13 owner-promotion interface
- **Blocks:** any future autonomy stage promotion

## Objective

Implement the currently fail-closed `OWNER-AUTONOMY-PROMOTION autonomy-promotion-1` issuer/ingestion/verifier.

This task must not enable autonomy.

## Required binding

Authorization must bind:

- repository;
- structural harness hash;
- activation PR;
- exact activation PR head;
- requested stage;
- maximum risk = L2;
- daily cap;
- owner login;
- owner numeric ID;
- timestamp;
- nonce;
- rationale.

## Authentication

Use actual GitHub owner identity and explicitly allowed ChatGPT connector transport.

Shape-valid JSON alone is not authentication.

## Runtime defense-in-depth

`stage_control` must independently verify returned:

- `status=PASS`;
- `authenticated=true`;
- `fixture_only=false`;
- repository;
- harness hash;
- activation PR;
- exact head;
- stage;
- L2 ceiling;
- daily cap;
- owner identity;
- freshness;
- nonce/replay state;
- revocation state.

Do not accept a generic `authenticated=true` result without matching the runtime context.

## Negative tests

- [ ] fixture authorization;
- [ ] wrong harness;
- [ ] wrong activation head;
- [ ] wrong stage;
- [ ] L3 ceiling;
- [ ] changed cap;
- [ ] stale authorization;
- [ ] replayed nonce;
- [ ] owner NO/revocation;
- [ ] wrong connector;
- [ ] Bot actor;
- [ ] model-created ledger JSON.

Every case fails closed.

## Done when

The verifier exists and passes tests, but autonomy remains disabled.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.
