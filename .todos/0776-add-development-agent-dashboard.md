# Add Development Agent Dashboard

- **ID:** 0776
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** medium
- **Depends:** 0762, 0764, 0770, 0771, 0775

## Problem

The coding-agent system needs a human control plane inside the Investment Dashboard so candidate rationale, risk, progress and evidence are visible without inspecting logs or Git manually.

## Scope and acceptance

- [ ] Add a read-only Development Agent dashboard section showing candidate queue, value/risk, source, stage, TODO, branch/PR, latest reviewer result and deployment/outcome state.
- [ ] Provide candidate detail with evidence, proposed change, affected files/components, risk reasons, acceptance criteria and run history.
- [ ] Show explicit badges for `NEEDS_HUMAN`, high-risk financial logic, blocked operations, stale evidence and failed gates.
- [ ] Provide links to GitHub PR/CI/evidence where available without exposing credentials.
- [ ] Keep development-agent data visually and structurally separate from portfolio recommendations so users cannot confuse software proposals with investment actions.
- [ ] Support filtering/sorting by status, risk, category and source.
- [ ] Use existing dashboard styling/components where practical and preserve current investment-page performance.

## QA requirements

- [ ] API/render tests cover empty state, mixed statuses, stale evidence, long titles and missing external links.
- [ ] Browser tests verify no investment tables are mutated by dashboard reads.
- [ ] Desktop and mobile rendering smoke tests pass.
- [ ] Full suite passes.

## Implementation guardrails

- Initial dashboard is read-only; approval controls are deferred to 0783.
- Do not embed raw untrusted model HTML.
- Do not fetch large logs on initial page load.

## Numbering history

Renumbered from coding-agent task 0761 to 0776; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/dashboard.py; serve.py; generate_dashboard.py`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
