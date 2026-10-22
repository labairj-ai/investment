# Detect Financial-Logic Changes in Agent Diffs

- **ID:** 0774
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0761, 0767, 0773

## Problem

Path-based risk classification can miss indirect changes to investment behavior. A semantic detector is needed to identify modifications that affect recommendations, portfolio arithmetic, covered calls, risk, learning or execution even when they occur in shared helpers.

## Scope and acceptance

- [ ] Define a protected behavioral surface covering recommendation generation, Advisor decision contracts, Critic/policy, position sizing, covered-call economics, tax/lot logic, risk previews, learning/promotion, order/fill/intent state and broker interfaces.
- [ ] Combine path rules, dependency/import reachability, protected symbol manifests and existing behavioral fingerprints where available.
- [ ] Classify any candidate touching the protected surface as at least `L4`; account/execution mutation surfaces classify as `L5`.
- [ ] Detect changed config/schema/constants that alter protected behavior without editing protected Python modules directly.
- [ ] Emit a machine-readable manifest of matched protected components and reasons.
- [ ] Version the protected-surface contract and require explicit review when components are added or removed.
- [ ] Integrate detection into pre-build planning, pre-review and pre-PR checks.

## QA requirements

- [ ] Mutation tests alter representative constants/helpers outside obvious protected paths and must still trigger.
- [ ] Existing CC behavioral-contract tests remain unchanged and pass.
- [ ] False-negative adversarial fixtures are prioritized over minimizing false positives.
- [ ] Full suite passes.

## Implementation guardrails

- LLM classification may raise but never lower semantic detector results.
- Do not use file-name heuristics alone.
- Protected-surface changes never become autonomous low-risk work.

## Numbering history

Renumbered from coding-agent task 0759 to 0774; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/policy.py: protected_graph/whole_diff`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
