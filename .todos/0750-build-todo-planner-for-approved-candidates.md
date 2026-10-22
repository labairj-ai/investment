# Build TODO Planner for Approved Candidates

- **ID:** 0750
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0745, 0747, 0749

## Problem

Approved improvement candidates need to be translated into the repository's existing `.todos/*.md` contract before code generation begins.

## Scope and acceptance

- [ ] Implement a Planner that inspects the approved candidate, relevant repository files, architecture docs and tests before proposing a TODO.
- [ ] Generate TODOs in the repository's canonical format with ID, backlog status, creation date, priority, dependencies, problem, scope/acceptance, QA requirements, implementation guardrails and source.
- [ ] Require acceptance criteria to be externally verifiable and avoid vague goals such as 'improve' without measurable behavior.
- [ ] Determine dependencies from active TODOs and repository architecture; detect dependency cycles before writing.
- [ ] Assign the next available TODO ID atomically or through a collision-safe reservation mechanism.
- [ ] Classify risk before finalizing the TODO and embed or reference the required gates.
- [ ] Require human approval of generated TODOs during the initial maturity phase; planner output alone cannot authorize implementation.

## QA requirements

- [ ] Round-trip tests parse generated TODOs with existing TODO consistency tooling.
- [ ] Concurrency tests prove two Planner runs cannot allocate the same ID.
- [ ] Golden examples cover UI, refactor, bug fix and high-risk investment work.
- [ ] Full suite and TODO consistency gate pass.

## Implementation guardrails

- Planner must not modify implementation code.
- Do not silently edit existing human-authored TODO acceptance criteria.
- If repository evidence is insufficient, produce `NEEDS_HUMAN` rather than inventing requirements.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
