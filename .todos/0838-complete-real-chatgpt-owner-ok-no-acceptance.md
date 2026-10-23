# TODO 0838 — Complete Real ChatGPT Owner OK/NO Acceptance

- **ID:** 0838
- **Status:** backlog
- **Priority:** critical
- **Risk:** L5 — owner authority
- **Parent:** 0827
- **Depends:** 0835
- **Blocks:** 0841, 0842

## Objective

Prove the actual ChatGPT → GitHub → Development Agent owner workflow rather than fixtures.

## Pilot PR

Create a disposable L0 documentation-only PR.

## OK path

- [ ] ChatGPT reviews exact head.
- [ ] Exact-head CI PASS.
- [ ] Owner says `OK`.
- [ ] Structured `OWNER-REVIEW solo-owner-2` created.
- [ ] GitHub object verifies owner login, owner numeric ID, type User, ChatGPT connector ID `1144995`, and slug `chatgpt-codex-connector`.
- [ ] Development ledger ingests exact-head approval.
- [ ] Owner gate PASS.
- [ ] Exact reviewed SHA merges.
- [ ] GitHub records owner as merge actor.
- [ ] `auto_merge=null`.

## NO path

Run a separate disposable head:

- [ ] owner says NO;
- [ ] merge admission blocked;
- [ ] no deployment admission;
- [ ] NO supersedes older OK where appropriate.

## Negative cases

- [ ] changed head after OK;
- [ ] edited comment;
- [ ] replayed nonce;
- [ ] wrong user;
- [ ] Bot user;
- [ ] wrong connector ID;
- [ ] wrong connector slug;
- [ ] wrong PR;
- [ ] wrong SHA;
- [ ] missing risk acknowledgment.

## Deployment authorization acceptance

Exercise `OWNER-DEPLOY deployment-1` against a non-production adapter:

- [ ] valid exact authorization accepted;
- [ ] stale SHA rejected;
- [ ] wrong merge rejected;
- [ ] expired authorization rejected;
- [ ] missing merged-main CI rejected.

## Done when

0827 can close with real GitHub evidence.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.
