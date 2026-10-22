# Build Improvement Scout

- **ID:** 0763
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0762

## Problem

A continuous coding agent needs a bounded discovery process that identifies worthwhile work without immediately modifying code or creating an endless stream of speculative features.

## Scope and acceptance

- [ ] Implement a read-only Scout that gathers signals from approved sources: active TODOs, recent completed work, git history, CI/test failures, application errors, performance/health metrics, TODO/FIXME markers and explicitly captured user feedback.
- [ ] Have the Scout produce structured candidate proposals only; it must not edit source files, create branches, deploy, merge or mutate investment state.
- [ ] Require every proposal to include evidence, user/problem impact, affected area, estimated scope, likely validation method and duplicate-candidate check.
- [ ] Cap proposals per run and enforce diversity so repeated feature-addition ideas cannot crowd out reliability, simplification, removal, refactor or accessibility work.
- [ ] Support discovery categories `FIX`, `SIMPLIFY`, `REMOVE`, `CONSOLIDATE`, `REFACTOR`, `OPTIMIZE`, `TEST`, `DOCUMENT` and `ADD`.
- [ ] Suppress candidates lacking concrete repository or operational evidence; speculative ideas may be recorded separately as low-confidence suggestions but cannot auto-enter implementation.
- [ ] Produce deterministic run metadata and trace which source signals generated each candidate.

## QA requirements

- [ ] Fixture-based Scout tests cover each input source and duplicate suppression.
- [ ] Prove Scout performs no repository writes or production DB mutations.
- [ ] Run with network/model failures and verify partial evidence cannot silently become an approved candidate.
- [ ] Full suite passes.

## Implementation guardrails

- Initial Scout cadence is manual/on-demand; scheduling is deferred to 0782.
- Do not reward the Scout for number of candidates generated.
- Missing telemetry must be reported as unavailable rather than inferred.

## Numbering history

Renumbered from coding-agent task 0748 to 0763; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/discovery.py: scout`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
