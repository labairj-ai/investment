# Score Coding-Agent Improvement Effectiveness

- **ID:** 0764
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0749, 0763

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

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
