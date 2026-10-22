# Review and Explicitly Authorize Bounded L0–L2 Autonomous Operation

- **ID:** 0802
- **Status:** backlog
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** 0801, 0794

## Problem

The autonomous implementation path exists but is intentionally disabled.

Activation should be a separate human governance decision made only after real prospective supervised evidence meets the required threshold.

## Scope and acceptance

- [ ] Review all three supervised pilot receipts and failures.
- [ ] Confirm current harness/config/contract hash matches pilot eligibility.
- [ ] Confirm technical certification remains current.
- [ ] Confirm GitHub effective protection remains PASS.
- [ ] Confirm authentic production snapshot evidence remains current.
- [ ] Confirm observation requirement ≥7 calendar days.
- [ ] Confirm minimum qualifying supervised successes ≥3.
- [ ] Confirm `auto_merge=false`.
- [ ] Confirm `required_human_merge=true`.
- [ ] Confirm autonomous maximum risk remains `L2`.
- [ ] Confirm daily implementation cap remains bounded.
- [ ] Confirm emergency-stop and environment kill switch function.
- [ ] Perform a separate reviewed configuration change to enable `autonomous_implementation`.
- [ ] After activation, allow autonomous progression only through PR creation.
- [ ] Continue requiring human merge and deployment.

## QA requirements

- [ ] L0 autonomous task can reach PR_OPEN.
- [ ] L2 autonomous task can reach PR_OPEN.
- [ ] L3 autonomous start is denied.
- [ ] L4/L5 Builder start is denied.
- [ ] Kill switch immediately blocks new autonomous starts.
- [ ] Failed/stale technical certification immediately blocks new starts.
- [ ] GitHub protection failure immediately blocks new starts.
- [ ] Agent cannot merge or deploy.
- [ ] Agent cannot modify its own governance/protection configuration.

## Implementation guardrails

- Do not expand beyond L0–L2 in this phase.
- Do not enable auto-merge.
- Do not allow autonomous financial logic changes.
- Future expansion requires a new separately reviewed evidence-backed epic.

## Source

User-supplied 2026-10-22 development-agent operational acceptance phase. Requirements and dependencies preserved; backlog creation does not authorize implementation or activation.
