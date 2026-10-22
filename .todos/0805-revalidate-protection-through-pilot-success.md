# TODO 0805 — Revalidate GitHub Protection Through Merge and Pilot Success

- **ID:** 0805
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** high
- **Depends:** 0797
- **Blocks:** 0801

## Problem

GitHub protection is verified at execution admission, publication and PR creation, but qualifying pilot evidence can later be recorded without proving that effective protections remained valid through review and merge.

A pilot must not qualify if protections were weakened after the agent started.

## Scope and acceptance

- [ ] Require fresh effective-protection evidence before:
  - supervised/autonomous start
  - branch publication
  - PR creation/update
  - PR disposition acceptance
  - merge recording
  - deployment observation
  - operational pilot success
- [ ] Bind each protection observation to:
  - GitHub identity
  - repository
  - timestamp
  - normalized effective policy
  - raw evidence hash
- [ ] Require protection evidence to satisfy configured maximum age.
- [ ] Require the same non-bypass coding-agent identity throughout the candidate lifecycle.
- [ ] If protections change materially, transition candidate to `NEEDS_HUMAN`.
- [ ] If protection evidence becomes unavailable, fail closed.
- [ ] Prevent `record_merge()` from succeeding without fresh protection PASS.
- [ ] Prevent `record_success()` from counting a pilot without fresh protection PASS.
- [ ] Surface protection drift in dashboard history.

## QA requirements

- [ ] Protection PASS at start then FAIL before merge → pilot cannot qualify.
- [ ] Agent gains admin permission before merge → merge evidence rejected.
- [ ] Ruleset bypass added after PR creation → pilot success rejected.
- [ ] Stale protection receipt → rejected.
- [ ] Stable protection across lifecycle → accepted.
- [ ] Protection drift creates explicit audit evidence.

## Implementation guardrails

- Development Agent may observe protections only.
- It must never repair or change protections itself.
- No cached PASS may survive beyond configured freshness limits.

## Source

User-supplied 2026-10-22 trust-boundary code-review follow-up. Backlog creation does not authorize implementation, promotion, pilot execution or autonomy activation.

## Implementation checkpoint — 2026-10-22

Implementation is on `codex/trust-boundary-0803-0809`; see the
[implementation plan](../docs/plans/development-agent-trust-boundaries-0803-0809.md)
and [trust-boundary contract](../docs/development-agent-trust-boundaries.md).
Source/fixture validation does not close environmental acceptance. This TODO remains
open pending its complete QA, required human decisions and exact-head CI evidence.
