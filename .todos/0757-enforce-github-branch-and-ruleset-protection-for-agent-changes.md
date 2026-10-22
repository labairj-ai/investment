# Enforce GitHub Branch and Ruleset Protection for Agent Changes

- **ID:** 0757
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0746, 0756

## Problem

Application-side rules are insufficient if an agent credential can bypass them at GitHub. Repository protections must make the intended review and status boundaries enforceable outside the agent process.

## Scope and acceptance

- [ ] Document and configure the desired protected-main/ruleset policy for agent-generated changes: PR required, required CI/status checks, conversation resolution and restricted direct push.
- [ ] Ensure the coding-agent identity cannot bypass required review for `L3+` work and cannot force-push protected branches.
- [ ] Define which low-risk levels may eventually qualify for auto-merge, but keep auto-merge disabled until separate evidence authorizes it.
- [ ] Require current branch status checks rather than stale successful runs from an older SHA.
- [ ] Document break-glass administration and audit requirements without embedding admin credentials.
- [ ] Add a repository-side verification script/API check that reports whether required protections are actually active.
- [ ] Fail scheduled autonomous implementation closed if required protections are absent or cannot be verified.

## QA requirements

- [ ] Verification tests mock protected, partially protected and unprotected repositories.
- [ ] Production rollout evidence records actual GitHub settings/status checks.
- [ ] Existing CI remains green.
- [ ] Manual break-glass path is documented and independently auditable.

## Implementation guardrails

- Do not have the agent grant itself permissions or alter rulesets.
- If connector/app permissions prevent verification, report `UNAVAILABLE` and stop autonomous PR promotion.
- Do not weaken existing release gates.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
