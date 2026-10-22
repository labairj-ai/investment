# Schedule Daily Improvement-Agent Discovery

- **ID:** 0782
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** medium
- **Depends:** 0763, 0764, 0775

## Problem

Once discovery and scoring are proven manually, the Scout can run on a schedule. Scheduling should create a bounded queue, not a permanently running self-modifying process.

## Scope and acceptance

- [ ] Add a daily scheduled Scout run using the project's established scheduler pattern, with explicit America/New_York semantics and DST-safe time utilities.
- [ ] Run discovery/scoring only; scheduled operation must not automatically implement work until later governance explicitly enables that maturity level.
- [ ] Use a lock/idempotency key so restarts or overlapping timers cannot duplicate a run.
- [ ] Cap new candidates and maintain a maximum active backlog; when full, report rather than continue generating work.
- [ ] Record schedule slot, start/end, inputs, candidate counts and failures in the run ledger.
- [ ] Retry transient failures with bounded attempts and no model retry storm.
- [ ] Provide a manual command for on-demand discovery using the same code path.

## QA requirements

- [ ] Scheduler tests cover DST, restart, duplicate slot and failure/retry behavior.
- [ ] Scheduled run performs no source-code or production-data writes beyond the development ledger/candidate store.
- [ ] Full suite passes.

## Implementation guardrails

- Do not run continuously or more frequently merely because compute is available.
- Backlog limits must be enforced before model-intensive discovery.
- Implementation remains human-triggered at this stage.

## Numbering history

Renumbered from coding-agent task 0767 to 0782; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/scheduler.py; systemd/development-scout.*`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
