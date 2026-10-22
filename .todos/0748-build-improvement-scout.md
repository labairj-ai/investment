# Build Improvement Scout

- **ID:** 0748
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0747

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

- Initial Scout cadence is manual/on-demand; scheduling is deferred to 0767.
- Do not reward the Scout for number of candidates generated.
- Missing telemetry must be reported as unavailable rather than inferred.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
