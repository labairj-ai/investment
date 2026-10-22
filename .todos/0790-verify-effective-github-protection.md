# Verify Effective GitHub Protection Across Branch Protection and Rulesets

- **ID:** 0790
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0772

## Problem

Current GitHub protection verification primarily depends on classic branch-protection API results and then separately inspects rulesets. Modern repository or organization rulesets may enforce equivalent protections even when the classic branch-protection endpoint is absent.

The coding agent needs to know the effective permissions of its actual identity.

## Scope and acceptance

- [ ] Build a canonical effective-protection evaluator covering:
  - classic branch protection
  - repository rulesets
  - inherited/organization rulesets when visible
  - bypass actors
  - authenticated coding-agent identity
- [ ] Determine whether the agent identity can:
  - push directly to `main`
  - bypass required PR review
  - bypass required status checks
  - force push
  - delete protected refs
  - bypass conversation resolution
  - self-approve
- [ ] Require current-head CI/status checks.
- [ ] Require at least one independent approving review.
- [ ] Require stale-review dismissal.
- [ ] Require last-push approval where supported.
- [ ] Require no coding-agent bypass authority.
- [ ] Treat incomplete API visibility as `UNAVAILABLE`, never PASS.
- [ ] Record raw evidence references plus normalized effective-policy result.
- [ ] Add an operator-readable explanation for every failing requirement.
- [ ] Preserve auto-merge=false.

## QA requirements

- [ ] Classic branch protection only → correctly evaluated.
- [ ] Ruleset-only protection → correctly evaluated.
- [ ] Both systems active → strictest effective result wins.
- [ ] Active bypass actor → fail.
- [ ] Unknown/inaccessible organization rules → unavailable/fail closed.
- [ ] Agent with admin bypass → fail.
- [ ] Correct non-bypass development identity → PASS.
- [ ] Full suite passes.

## Implementation guardrails

- Do not modify repository protections from the development agent.
- Protection configuration remains a human administrator operation.
- Do not infer permissions solely from repository role names.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.
