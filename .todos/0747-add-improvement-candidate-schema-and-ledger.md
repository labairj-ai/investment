# Add Improvement Candidate Schema and Ledger

- **ID:** 0747
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0745, 0746

## Problem

Continuous improvement needs a durable record of what the agent considered, why it considered it, and what happened next. Without a candidate ledger, discovery becomes unauditable and repetitive.

## Scope and acceptance

- [ ] Add a development-improvement candidate model with immutable candidate ID, creation time, source, title, problem statement, evidence references, proposed outcome, estimated scope, value score, risk score, status and lineage.
- [ ] Support candidate sources including user request, test/CI failure, telemetry, error log, TODO/FIXME, architecture debt, performance, accessibility/mobile review and agent discovery.
- [ ] Define lifecycle states such as `DISCOVERED`, `PLANNED`, `APPROVED`, `REJECTED`, `DEFERRED`, `BUILDING`, `PR_OPEN`, `DEPLOYED`, `ROLLED_BACK` and `CLOSED` with valid transitions.
- [ ] Store candidate records separately from investment decision/recommendation learning data; development-agent evidence must never enter portfolio learning cohorts.
- [ ] Preserve raw evidence references and structured reasoning summaries without storing secrets or unbounded logs.
- [ ] Make candidate identity idempotent enough to suppress rediscovery of the same unresolved issue while allowing a materially changed recurrence.
- [ ] Expose read-only repository/API helpers for listing and inspecting candidates.

## QA requirements

- [ ] Migration is idempotent and safe against an existing production snapshot.
- [ ] Lifecycle transition tests reject invalid backward/skipping transitions unless an explicit administrative path is used.
- [ ] Development ledger writes cannot alter recommendation, order, fill, thesis, portfolio or covered-call records.
- [ ] Full suite and migration tests pass.

## Implementation guardrails

- Prefer a dedicated development-control store/table namespace over reusing investment recommendation tables.
- Never derive candidate success from investment returns.
- Do not copy sensitive log payloads into the candidate ledger.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
