# TODO 0819 — Add ChatGPT OK/NO Owner-Attestation Workflow

- **ID:** 0819
- **Status:** in-progress
- **Priority:** high
- **Risk:** L5 — human authority / merge governance
- **Depends:** 0816, 0817
- **Blocks:** 0822, 0823, 0824

## Problem

The intended owner workflow is:

1. Agents produce a PR and evidence.
2. ChatGPT independently reviews the actual PR, diff and CI.
3. ChatGPT recommends `OK` or `NO`.
4. The repository owner says `OK` or `NO` in ChatGPT.
5. An authenticated GitHub action records that owner decision.
6. Exact-head validation is rechecked.
7. The owner-authorized merge occurs.
8. Deployment proceeds through a separate controlled path.

The current Development Agent only recognizes owner attestation through local interactive CLI or Tailscale Serve.

It does not natively recognize an owner-authorized GitHub action generated through the connected GitHub account.

## Scope and acceptance

- [ ] Add a GitHub-backed owner-attestation source.
- [ ] Do not give the Development Agent the owner's GitHub credential.
- [ ] Keep agent GitHub identity separate from owner identity.
- [ ] Bind attestation to:
  - repository,
  - PR number,
  - exact current head SHA,
  - risk level,
  - decision,
  - timestamp,
  - single-use nonce,
  - rationale when required,
  - L4 financial acknowledgment when required,
  - L5 execution acknowledgment when required.
- [ ] Verify the GitHub actor is the configured personal repository owner.
- [ ] Verify repository owner ID as well as login.
- [ ] Verify the PR still targets `main`.
- [ ] Verify the PR head has not changed.
- [ ] Reject stale approvals.
- [ ] Reject approvals written by agent/service identities.
- [ ] Reject approvals from bots.
- [ ] Reject approvals from other collaborators.
- [ ] Reject unstructured comments that happen to contain the word APPROVE.
- [ ] Preserve a machine-readable audit record in the Development Agent ledger.
- [ ] Record the originating GitHub object ID and URL.
- [ ] Make duplicate/replayed approval records idempotent or fail closed.
- [ ] Allow `NO` / request-changes decisions through the same channel.
- [ ] Ensure an owner decision does not automatically merge unless the explicit workflow is currently executing under owner authorization.
- [ ] Ensure owner approval cannot enable auto-merge.
- [ ] Ensure merge is performed only against the approved exact head.

## Recommended GitHub representation

Use a deliberately formatted owner-authored PR comment or other GitHub-native owner-authenticated object containing a versioned payload such as:

`OWNER-REVIEW solo-owner-2`

with exact head/risk/nonce/decision metadata.

The Development Agent must validate the GitHub API identity of the actor rather than trusting text alone.

If a stronger GitHub-native attestation mechanism is available, prefer it.

## Required tests

- [ ] Owner-authored exact-head approval validates.
- [ ] Owner-authored request-changes validates.
- [ ] Agent-authored identical text fails.
- [ ] Bot-authored identical text fails.
- [ ] Other-user identical text fails.
- [ ] Modified PR head makes approval stale.
- [ ] Reused nonce fails.
- [ ] Wrong repository fails.
- [ ] Wrong PR fails.
- [ ] Lowered risk fails.
- [ ] L4 missing financial ack fails.
- [ ] L5 missing execution ack fails.
- [ ] Owner approval does not itself merge.
- [ ] Merge call rejects an expected-head mismatch.

## QA requirements

- [ ] Exercise the complete real flow on a low-risk test PR.
- [ ] ChatGPT recommendation → owner OK → GitHub attestation → exact-head verification → merge.
- [ ] Test NO path.
- [ ] Test head-change-after-OK path.
- [ ] Test concurrent push during approval.
- [ ] Record audit evidence without storing private credentials.

## Implementation guardrails

- Do not expose ChatGPT conversation content to the Development Agent.
- Do not store OAuth tokens in the repository.
- Do not let the Builder write owner attestations.
- Do not equate PR authorship with approval.
- Do not require a second human.
- Keep financial and execution gates unchanged.

## Done when

- [ ] A real PR can be approved solely through the owner's OK/NO workflow in ChatGPT plus authenticated GitHub action.
- [ ] No GitHub UI interaction is required from the owner.
- [ ] Exact-head owner approval is visible in the Development Agent ledger.
- [ ] Merge remains impossible without fresh owner approval.
