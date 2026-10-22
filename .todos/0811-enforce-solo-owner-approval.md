# TODO 0811 — Update AGENTS.md and Governance Checks for Solo-Owner Approval

- **ID:** 0811
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** 0810
- **Blocks:** 0812

## Problem

Policy text is insufficient if repository checks and Development Agent logic still require the approving GitHub identity to differ from the PR author. Code and documentation must enforce the same solo-owner authority model.

## Scope and acceptance

- [ ] Update root AGENTS.md and Development Agent independent-human-review documentation.
- [ ] Update scripts/check_agent_contract.py and scripts/check_development_agent.py as necessary.
- [ ] Update review/merge eligibility logic that requires reviewer GitHub identity != author GitHub identity.
- [ ] Replace identity inequality with authenticated human owner approval.
- [ ] Preserve reviewer-model independence from Builder model.
- [ ] Preserve authenticated owner identity evidence and exact-head review binding.
- [ ] Bind owner approval to the current PR head SHA; require fresh approval after material head changes where applicable.
- [ ] Preserve all L4/L5 domain-specific requirements.
- [ ] Add explicit tests for solo-owner behavior.

## QA requirements

- [ ] Owner authors PR and approves current exact head: permitted.
- [ ] Coding agent attempts approval: rejected.
- [ ] Reviewer model PASS without owner approval: rejected.
- [ ] CI PASS without owner approval: rejected.
- [ ] Stale-head owner approval: rejected/reapproval required.
- [ ] L4 still requires financial-domain evidence.
- [ ] L5 still requires execution/account safeguards.
- [ ] auto_merge remains false.
- [ ] Full repository suite passes.

## Implementation guardrails

- Owner approval must come from authenticated human action.
- Do not infer approval from commit authorship.
- Development Agent must not generate or synthesize the approval event.

## Implementation status — 2026-10-22

Runtime merge/pilot gates consume authenticated exact-head owner attestations; independent model review and financial controls preserved. Pending review, exact-head validation and integration onto governance-enabled main.
