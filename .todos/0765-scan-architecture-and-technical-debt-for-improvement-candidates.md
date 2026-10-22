# Scan Architecture and Technical Debt for Improvement Candidates

- **ID:** 0765
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** medium
- **Depends:** 0748, 0749

## Problem

The Scout should identify maintainability problems that tests may not expose, but architecture scanning needs objective evidence to avoid arbitrary refactoring.

## Scope and acceptance

- [ ] Add deterministic architecture signals such as oversized modules, import cycles, duplicated helpers, dead code markers, TODO/FIXME density, repeated exception patterns and high-change/high-defect hotspots.
- [ ] Use repository history and static analysis where available to attach evidence instead of relying only on model impressions.
- [ ] Generate refactor candidates only when a concrete maintainability or reliability mechanism is identified.
- [ ] Distinguish safe internal refactors from behavior-affecting changes and pass all candidates through the normal risk classifier.
- [ ] Cap architecture candidates per Scout run and deduplicate recurring unresolved debt.
- [ ] Provide a 'do nothing' outcome when no debt exceeds configured evidence thresholds.
- [ ] Allow human-maintained exclusions for intentional large modules/patterns with documented rationale.

## QA requirements

- [ ] Golden fixtures include true and false-positive debt patterns.
- [ ] Scanner is read-only and deterministic for a pinned SHA/config.
- [ ] Full suite passes.

## Implementation guardrails

- Do not refactor solely to satisfy arbitrary line-count targets.
- Do not auto-split modules whose boundaries would increase coupling.
- Architecture score cannot override user-facing or safety priorities.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
