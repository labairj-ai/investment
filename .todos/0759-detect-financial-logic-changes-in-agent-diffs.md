# Detect Financial-Logic Changes in Agent Diffs

- **ID:** 0759
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0746, 0752, 0758

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

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
