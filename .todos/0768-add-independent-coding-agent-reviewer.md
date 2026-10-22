# Add Independent Coding-Agent Reviewer

- **ID:** 0768
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0760, 0761, 0767

## Problem

A builder reviewing its own work creates correlated failure. Candidate changes need an independent reviewer context that judges the diff against the original TODO and repository invariants.

## Scope and acceptance

- [ ] Implement a reviewer role that receives the original TODO, base SHA, candidate diff, test evidence and relevant repository contracts, but not the builder's private rationale as authoritative evidence.
- [ ] Return structured findings with severity, file/location, violated requirement, evidence and disposition: `PASS`, `REQUEST_CHANGES` or `NEEDS_HUMAN`.
- [ ] Review for acceptance-criteria coverage, regression risk, architecture fit, security, data mutation, test quality, mobile/accessibility requirements when applicable and investment-domain guardrails.
- [ ] Require deterministic pre-review checks before model review so obvious forbidden files, missing tests or risk misclassification fail without model discretion.
- [ ] Prevent the reviewer from modifying the candidate branch directly.
- [ ] Record reviewer provider/model/version independently from the builder.
- [ ] High-risk investment/execution changes can never receive final merge authorization solely from this reviewer.

## QA requirements

- [ ] Golden diffs include good change, missing acceptance criterion, weakened test, hidden production write and unrelated scope expansion.
- [ ] Prove reviewer cannot mutate the worktree/branch.
- [ ] Reviewer unavailability yields `NEEDS_HUMAN`, not PASS.
- [ ] Full suite passes.

## Implementation guardrails

- Do not share builder self-evaluation as ground truth.
- Reviewer findings must be auditable and linked to concrete evidence.
- Severity downgrades require an explicit subsequent review event.

## Numbering history

Renumbered from coding-agent task 0753 to 0768; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/runner.py: review`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
