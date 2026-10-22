# Add Human Approval and Escalation Workflow

- **ID:** 0768
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0746, 0750, 0753, 0756, 0761, 0762, 0760

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

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
