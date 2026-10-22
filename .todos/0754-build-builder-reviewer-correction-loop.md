# Build Builder-Reviewer Correction Loop

- **ID:** 0754
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0752, 0753

## Problem

The agent should be able to correct bounded review findings without requiring a new manual coding session, but the correction loop must terminate safely and preserve review lineage.

## Scope and acceptance

- [ ] Implement a bounded loop that sends actionable reviewer findings back to the builder and re-runs required validation before re-review.
- [ ] Carry forward unresolved findings by stable finding ID so they cannot disappear merely because wording changed.
- [ ] Require a fresh diff and fresh evidence for each iteration; record iteration number, changed files, findings resolved/new and stop reason.
- [ ] Set hard limits for iterations, cumulative changed lines, wall time and repeated identical failures.
- [ ] Escalate to `NEEDS_HUMAN` when findings conflict, scope must expand materially, the same high-severity finding repeats, or budgets are exhausted.
- [ ] Require final reviewer `PASS` plus deterministic gates before PR-ready status.
- [ ] Do not allow a correction iteration to change TODO acceptance criteria or risk level downward.

## QA requirements

- [ ] Tests cover one-pass success, successful correction, repeated failure, new regression, conflicting findings and budget exhaustion.
- [ ] Lineage survives process restart without duplicating iterations.
- [ ] Full suite passes.

## Implementation guardrails

- Correction does not imply merge approval.
- Never let the builder mark reviewer findings resolved without a subsequent independent review.
- Keep the loop scoped to the original TODO.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
