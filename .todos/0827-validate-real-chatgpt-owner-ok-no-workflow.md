# TODO 0827 — Validate the Real ChatGPT Owner OK/NO Workflow

- **ID:** 0827
- **Status:** in-progress
- **Priority:** critical
- **Risk:** L5 — owner authority
- **Depends:** 0819 implementation, PR #10 deployment
- **Blocks:** 0829, 0830, 0831

## Problem

The repository now supports owner-authored GitHub objects created through the ChatGPT Codex Connector, but this has only been fixture-tested under the new `solo-owner-2` protocol.

The exact workflow must be proven using the real connected GitHub account.

## Configuration

Provision external `DEV_AGENT_OWNER_BINDINGS` with:

- repository = `labairj-ai/investment`
- exact repository-owner login;
- exact repository-owner numeric ID;
- existing approved operator identities;
- explicitly allowlisted GitHub App:
  - ID `1144995`
  - slug `chatgpt-codex-connector`

## Live acceptance PR

Create a disposable L0 test PR containing only a harmless repository documentation change.

Required flow:

1. [ ] PR opened.
2. [ ] Exact-head CI green.
3. [ ] ChatGPT reviews actual diff.
4. [ ] ChatGPT recommends OK.
5. [ ] Owner replies `OK`.
6. [ ] Connector creates `OWNER-REVIEW solo-owner-2`.
7. [ ] GitHub API object shows:
   - owner login;
   - owner numeric ID;
   - `type=User`;
   - ChatGPT connector App ID/slug.
8. [ ] Development Agent ingests object read-only.
9. [ ] Ledger records exact-head `OWNER_REVIEW`.
10. [ ] Owner gate passes.
11. [ ] Merge is attempted using exact expected head.
12. [ ] GitHub records owner as merge actor.
13. [ ] Auto-merge remains null/disabled.

## Negative acceptance cases

- [ ] Say NO after an earlier OK; older approval becomes invalid.
- [ ] Push a new commit after OK; approval becomes stale.
- [ ] Wrong GitHub app fails.
- [ ] Wrong owner ID fails.
- [ ] Bot user fails.
- [ ] Edited owner comment fails.
- [ ] Replayed nonce fails.
- [ ] Owner review for one PR fails on another PR.
- [ ] Owner review for one SHA fails on another SHA.
- [ ] Missing L4 financial acknowledgment fails.
- [ ] Missing L5 execution acknowledgment fails.

## Deployment authorization validation

Also exercise a non-production/fixed test version of:

`OWNER-DEPLOY deployment-1`

- [ ] correct ChatGPT connector accepted;
- [ ] wrong app rejected;
- [ ] wrong owner rejected;
- [ ] expired authorization rejected;
- [ ] wrong merge SHA rejected;
- [ ] missing exact merged-main CI rejected.

## Guardrails

- Use L0 documentation-only test PR.
- No financial behavior change.
- No production deployment required for owner-review validation.
- Do not weaken connector app allowlist.
- Do not treat the ChatGPT app itself as the human owner.
- Human owner ID/login remains authoritative.

## Done when

- [ ] Real ChatGPT OK/NO flow succeeds.
- [ ] Real NO/stale-head paths fail correctly.
- [ ] Evidence is recorded in Development Agent ledger.
- [ ] No GitHub UI action is required from the owner.

## Implementation / acceptance handoff — 2026-10-23

Preserved connector/human identity boundaries and strengthened exact CI identity in deployment admission. Real owner OK/NO, external bindings and live negative acceptance remain pending; no owner event was synthesized.

See [live operational acceptance](../docs/live-operational-acceptance.md) and the [sanitized live preflight](../docs/evidence/continuous-improvement-20261023/live-acceptance-preflight.json). This task remains in progress until every required live acceptance and release gate is satisfied.
