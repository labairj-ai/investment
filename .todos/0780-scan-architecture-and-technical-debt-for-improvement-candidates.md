# Scan Architecture and Technical Debt for Improvement Candidates

- **ID:** 0780
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** medium
- **Depends:** 0763, 0764

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

## Numbering history

Renumbered from coding-agent task 0765 to 0780; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/discovery.py: architecture_signals`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
