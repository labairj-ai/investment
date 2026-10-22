# Score Coding-Agent Improvement Effectiveness

- **ID:** 0779
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0764, 0778

## Problem

The agent should learn which kinds of software changes actually help this application, but the reward function must avoid encouraging feature volume, test gaming or risky financial changes.

## Scope and acceptance

- [ ] Define effectiveness dimensions including acceptance success, defect recurrence, rollback rate, reviewer findings, operational health, user acceptance/usage when available, complexity added/removed and maintenance burden.
- [ ] Compute effectiveness only after an appropriate observation state; keep `INSUFFICIENT_DATA` separate from failure.
- [ ] Compare candidate category/source/risk bands over time without allowing the score to auto-change financial behavior or governance thresholds.
- [ ] Track feature additions separately from fixes/simplifications/removals to detect feature inflation.
- [ ] Use effectiveness as a Scout prioritization input only after minimum evidence thresholds are met.
- [ ] Version the effectiveness contract and retain historical scores under the version that produced them.
- [ ] Expose aggregate effectiveness in the Development Agent dashboard without presenting it as investment performance.

## QA requirements

- [ ] Fixture tests cover success, rollback, unused feature, simplification, insufficient data and mixed evidence.
- [ ] Guard tests prove the metric cannot lower risk class or bypass human approval.
- [ ] Full suite passes.

## Implementation guardrails

- Do not optimize on commit count, lines changed or candidate count.
- Do not treat user silence as success.
- Keep development effectiveness isolated from portfolio champion/challenger learning.

## Numbering history

Renumbered from coding-agent task 0764 to 0779; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/outcomes.py: effectiveness/aggregate`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
