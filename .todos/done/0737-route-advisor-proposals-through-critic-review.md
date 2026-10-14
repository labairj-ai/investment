# Route Advisor Proposals Through Critic Review

- **ID:** 0737
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0733, 0736

## Problem

Advisor-originated trade ideas currently bypass the same adversarial review used for agent recommendations. This allows a conversational proposal to reach a favorable verdict without deterministic vetoes or Critic review.

Advisor proposals need first-class governed review without pretending they originated from a producer agent.

## Proposed approach

- Add an `AdvisorProposal` contract that contains the normalized request, deterministic trade-impact result, thesis/candidate evidence references and source context hash.
- Add a Critic adapter that reuses the existing deterministic veto rules and LLM Critic where applicable.
- Persist no normal `Recommendation` row solely to obtain a Critic verdict unless the existing contract can represent `origin=advisor` without corrupting agent-learning semantics.
- Return `APPROVE`, `APPROVE_WITH_CAUTION`, `CHALLENGE`, or `VETO` plus confidence adjustment, objections and deterministic-veto provenance.
- Feed the Critic result back into the advisor actionability policy.

## Touches

- `agents/advisor/contracts.py`
- `agents/advisor/critic.py`
- `agents/critic_agent.py`
- `agents/contracts.py` only if a shared reviewable-proposal interface is needed
- `tests/`

## Implementation guardrails

- Reuse deterministic veto logic; do not clone it into advisor code.
- Advisor prose cannot suppress, rewrite or downgrade a deterministic Critic veto.
- Critic failure in Decision mode must fail closed to `REVIEW_REQUIRED` or `BLOCKED`; do not reuse a fail-open default that implies approval.
- Preserve existing agent Critic behavior unless an explicitly versioned shared change is required.
- Do not add advisor proposals to learning cohorts as if they were ordinary producer-agent recommendations unless a separate eligibility contract is defined.
- No trade intent or order may be created by this review stage.

## Done when

- [x] An advisor proposal that violates an existing deterministic veto receives the same veto class as the equivalent governed recommendation fixture.
- [x] Critic `VETO` can never result in advisor `ACTIONABLE`.
- [x] Critic `CHALLENGE` produces at most `REVIEW_REQUIRED`.
- [x] Critic runtime/LLM failure in Decision mode is fail-closed and visibly identified.
- [x] Existing producer-agent Critic tests continue to pass unchanged.
- [x] Advisor proposals are distinguishable from producer-agent recommendations in persisted/audit structures if persistence is introduced.
- [x] QA evaluation conducted: deterministic-veto parity, Critic failure-path tests and full `pytest tests/ -v --tb=short` pass with no regressions introduced.

## Completion evidence

Completed 2026-10-14. Implementation and acceptance fixtures are documented in
`docs/advisor-decision.md`; focused advisor QA: 55 passed. Full local suite:
2,529 passed, 16 existing skips, no failures. Exact baseline and CC behavioral
contract gates passed. Read-only production-snapshot canary passed with trading
state unchanged and degraded evidence held in review. Real GitHub Actions passed:
https://github.com/labairj-ai/investment/actions/runs/38552153244
