# Configure and Verify Non-Bypass GitHub Protection for Development-Agent Changes

- **ID:** 0797
- **Status:** backlog
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** 0790, 0796

## Problem

`main` is currently not effectively protected for development-agent operation, and the GitHub identity being used has administrative authority.

An autonomous or supervised coding identity must not be able to circumvent the controls intended to govern it.

## Scope and acceptance

- [ ] Configure effective protection for `main` using branch protection, rulesets or both.
- [ ] Require PR-based changes to `main`.
- [ ] Require current-head `test` / repository CI status.
- [ ] Require at least one independent approving review.
- [ ] Require stale-review dismissal.
- [ ] Require last-push approval where supported.
- [ ] Require conversation resolution.
- [ ] Disable force pushes and deletion of `main`.
- [ ] Ensure the coding-agent operational identity cannot bypass:
  - PR requirement
  - independent review
  - required status checks
  - conversation resolution
- [ ] Ensure the operational coding-agent identity does not have administrative/ruleset-management authority.
- [ ] Run the development-agent effective-protection verifier using the actual operational identity.
- [ ] Persist normalized and raw protection evidence.
- [ ] Require verifier status = `PASS`.

## QA requirements

- [ ] Direct push attempt to `main` by coding-agent identity is rejected.
- [ ] PR with failing CI cannot merge.
- [ ] PR without independent approval cannot merge.
- [ ] New push after approval invalidates/requires fresh review as configured.
- [ ] Coding-agent identity cannot edit/remove its own protection policy.
- [ ] Effective-protection check reports PASS using real GitHub APIs.

## Implementation guardrails

- Protection changes must be performed by a human administrator.
- Development-agent code may inspect protections but must never modify them.
- Break-glass access must remain separately documented and auditable.

## Source

User-supplied 2026-10-22 development-agent operational acceptance phase. Requirements and dependencies preserved; backlog creation does not authorize implementation or activation.
