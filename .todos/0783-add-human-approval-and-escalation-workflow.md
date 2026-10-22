# Add Human Approval and Escalation Workflow

- **ID:** 0783
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0761, 0765, 0768, 0771, 0776, 0777, 0775

## Problem

The initial coding-agent maturity model requires the user to approve proposed work and merges, and the system needs a first-class way to surface decisions that cannot safely be made autonomously.

## Scope and acceptance

- [ ] Add explicit human decision states for candidate approval/rejection/defer, TODO approval, review override/escalation and high-risk PR disposition.
- [ ] Expose bounded approval controls in the Development Agent dashboard with confirmation for high-risk actions and clear display of evidence/risk before action.
- [ ] Record actor, timestamp, prior state, decision, rationale when required and exact candidate/TODO/SHA context in the audit ledger.
- [ ] Require a fresh approval when material scope, risk level, acceptance criteria or head SHA changes after approval.
- [ ] Do not permit a human UI approval to bypass hard technical safety gates such as production mutation denial or execution restrictions.
- [ ] Support `NEEDS_HUMAN` reasons from Planner, Builder, Reviewer, GitHub protection verification and deployment/outcome checks.
- [ ] Make all approval endpoints CSRF/auth consistent with the dashboard's existing security model and reject replayed/stale decisions.

## QA requirements

- [ ] State-machine tests cover approve/reject/defer, stale SHA, changed scope, replay and unauthorized requests.
- [ ] Mobile browser tests cover approval UX without accidental tap acceptance.
- [ ] Audit lineage is immutable.
- [ ] Full suite passes.

## Implementation guardrails

- Human approval is explicit; absence of a response is never approval.
- High-risk financial/execution work remains governed by existing domain canaries in addition to this workflow.
- Do not add merge or deployment credentials to the browser.

## Numbering history

Renumbered from coding-agent task 0768 to 0783; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/store.py: decide/review_decision; dev_agent/dashboard.py`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
