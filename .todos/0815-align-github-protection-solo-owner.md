# TODO 0815 — Align GitHub Protection With Solo-Owner Governance

- **ID:** 0815
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** high
- **Depends:** 0811
- **Relates to:** 0797

## Problem

Protection must enforce the solo-owner model. Requiring a different approving GitHub account recreates a permanent blocker; removing review requirements entirely weakens human control.

## Scope and acceptance

- [ ] Configure GitHub protection/rulesets for the personal-repository model.
- [ ] Require PRs for protected changes and current-head CI.
- [ ] Require conversation resolution where useful.
- [ ] Disable force pushes and branch deletion.
- [ ] Prevent coding-agent identity from bypassing protection, merging or changing rulesets.
- [ ] Permit repository owner to perform final human merge.
- [ ] Do not require a second human account unless owner explicitly enables that rule.
- [ ] Update effective-protection verifier to understand this policy.
- [ ] Ensure verifier distinguishes owner merge authority from coding-agent bypass authority.

## QA requirements

- [ ] Coding-agent identity cannot directly push to main, merge or change rulesets.
- [ ] Owner can merge after required gates pass.
- [ ] Red CI prevents merge under normal workflow.
- [ ] Green CI plus explicit owner approval satisfies solo-owner policy.
- [ ] Protection verifier reports PASS under intended configuration.

## Implementation guardrails

- Distinguish human owner identity from any future dedicated agent GitHub identity.
- Do not grant agent administrator privileges.

## Implementation status — 2026-10-22

Read-only split-ruleset verifier and human administrator runbook prepared. Live inspection found no rulesets and current credentials are owner/admin. Dedicated agent identity, trusted owner-check App/controller, human protection configuration and live negative tests remain unavailable; no protection PASS claimed.
