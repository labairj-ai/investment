# Score Improvement Candidate Value and Risk

- **ID:** 0749
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0746, 0747, 0748

## Problem

Candidate selection should optimize useful outcomes, not raw feature volume. The agent needs a bounded scoring contract that favors user value, reliability and simplification while penalizing risk and uncertain evidence.

## Scope and acceptance

- [ ] Define transparent value dimensions such as user impact, defect severity, reliability, maintainability, performance, accessibility/mobile benefit and strategic fit.
- [ ] Define risk dimensions including financial-behavior impact, production mutability, data migration, architectural breadth, testability, rollback difficulty and evidence uncertainty.
- [ ] Separate deterministic risk classification from prioritization score; prioritization must never lower mandatory gates from TODO 0746.
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

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
