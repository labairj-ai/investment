# Bind GitHub Pull Requests to the Exact Sealed Head SHA

- **ID:** 0789
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0771, 0785

## Problem

PR handoff validates the local candidate branch and sealed evidence, but the remote GitHub PR head is not explicitly verified against the evidence receipt.

A PR description must never claim evidence for commit B while GitHub is actually reviewing commit A.

## Scope and acceptance

- [ ] Query GitHub after PR creation or update and retrieve:
  - PR number
  - head branch
  - head repository
  - `headRefOid` / exact head SHA
  - base branch
  - draft state
- [ ] Require remote PR head SHA == sealed evidence head SHA.
- [ ] Require remote base branch == expected protected `main`.
- [ ] Require remote head branch == the approved agent branch.
- [ ] Refuse to record `PR_OPEN` when remote head identity does not match.
- [ ] Record verified remote PR identity and SHA in the immutable ledger.
- [ ] Before later review/merge disposition, re-check remote head and invalidate stale evidence after additional pushes.
- [ ] A push after sealing must require fresh validation, Reviewer PASS and receipt.
- [ ] Updating an existing PR must not reuse stale evidence from an earlier commit.
- [ ] PR body must distinguish sealed/tested SHA from base SHA.

## QA requirements

- [ ] Remote head A with receipt B must fail.
- [ ] Matching head and receipt must pass.
- [ ] Existing PR advanced after receipt creation must return stale/NEEDS_HUMAN.
- [ ] Wrong base branch must fail.
- [ ] Wrong fork/repository identity must fail.
- [ ] Draft/readiness metadata remains accurate.
- [ ] Duplicate PR prevention remains intact.

## Implementation guardrails

- Do not force push to make GitHub match evidence.
- Do not rewrite evidence to match a changed PR.
- The code under review must match the code that passed validation.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.
