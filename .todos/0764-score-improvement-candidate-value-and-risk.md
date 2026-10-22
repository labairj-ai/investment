# Score Improvement Candidate Value and Risk

- **ID:** 0764
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0761, 0762, 0763

## Problem

Candidate selection should optimize useful outcomes, not raw feature volume. The agent needs a bounded scoring contract that favors user value, reliability and simplification while penalizing risk and uncertain evidence.

## Scope and acceptance

- [ ] Define transparent value dimensions such as user impact, defect severity, reliability, maintainability, performance, accessibility/mobile benefit and strategic fit.
- [ ] Define risk dimensions including financial-behavior impact, production mutability, data migration, architectural breadth, testability, rollback difficulty and evidence uncertainty.
- [ ] Separate deterministic risk classification from prioritization score; prioritization must never lower mandatory gates from TODO 0761.
- [ ] Add bonuses for simplification/removal when evidence supports them and penalties for feature complexity, duplicated capability and weak evidence.
- [ ] Return a structured scorecard with component scores, confidence, rationale and final ranking score.
- [ ] Use stable normalization and tie-breaking so repeated runs over unchanged inputs are reproducible.
- [ ] Support policy thresholds for `RECOMMEND`, `HUMAN_REVIEW`, `DEFER` and `REJECT` without auto-approving high-risk work.

## QA requirements

- [ ] Golden fixtures verify rankings for bugs, mobile UX, refactors, speculative features and financial-logic candidates.
- [ ] Adversarial tests ensure a high value score cannot bypass risk requirements.
- [ ] Score changes require versioning and regression fixtures.
- [ ] Full suite passes.

## Implementation guardrails

- Do not use investment P&L as a development-candidate reward signal.
- Keep scoring explainable; no opaque single LLM score should determine selection.
- Threshold changes require explicit review and evidence.

## Numbering history

Renumbered from coding-agent task 0749 to 0764; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/discovery.py: score`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
