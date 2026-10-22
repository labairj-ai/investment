# Persist Coding-Agent Run Ledger and Audit History

- **ID:** 0775
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0762, 0767, 0768, 0770

## Problem

Individual candidate records are not enough to reconstruct exactly what an autonomous development system did. Each planning, build, review and validation execution needs immutable lineage.

## Scope and acceptance

- [ ] Add a run ledger with run ID, candidate/TODO, role, provider/model, start/end times, base/head SHA, worktree identity, status, stop reason, parent run and evidence receipt.
- [ ] Record structured events for planning, build iterations, reviewer passes, blocked operations, PR creation, human decisions and deployment/outcome linkage.
- [ ] Make completed run records append-only; corrections create superseding events rather than rewriting history.
- [ ] Separate concise audit metadata from large artifacts/logs stored by reference.
- [ ] Expose read-only query helpers by candidate, TODO, SHA, status and time range.
- [ ] Retain enough lineage to reproduce why a PR was considered ready at a specific SHA.
- [ ] Add retention/archive policy that preserves critical evidence while bounding transient model/tool logs.

## QA requirements

- [ ] Append-only and lineage tests reject mutation of finalized runs.
- [ ] Crash recovery does not duplicate terminal events.
- [ ] Queries return deterministic ordering.
- [ ] Full suite and migration tests pass.

## Implementation guardrails

- Do not mix development-run events with investment decision episodes.
- Redact secret-bearing tool inputs/outputs before persistence.
- Audit records must survive dashboard/service restarts.

## Numbering history

Renumbered from coding-agent task 0760 to 0775; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/store.py: run_event/query_runs`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
