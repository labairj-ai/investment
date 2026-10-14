# Add Portfolio Advisor Decision Adversarial QA

- **ID:** 0741
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0737, 0738, 0739, 0740

## Problem

The Portfolio Advisor has recently gained important prompt-level protections, but there is no dedicated end-to-end decision QA suite proving that trade math, evidence authority, tax-lot handling, Critic review, risk preview and invalidation cannot be bypassed.

Before treating Decision mode as trustworthy, the system needs adversarial and production-canary evidence.

## Proposed approach

- Add a dedicated advisor decision test suite spanning parser, context, simulator, tax lots, policy, Critic, risk preview, persistence and API output.
- Build adversarial fixtures for prompt injection, stale data, mixed tax lots, target-vs-delta ambiguity, CC coverage, unsupported candidates, missing thesis, Critic failure and risk rejection.
- Add invariant tests proving LLM narrative cannot modify deterministic fields.
- Add a read-only production canary that executes representative decision scenarios against current data and records health without writing trading state.
- Add advisor health metrics for decision counts/states, gate failures, stale/invalid decisions and rendering/model failures.

## Touches

- `tests/test_advisor_*.py`
- `scripts/canary_advisor_decision.py`
- `serve.py` and/or dashboard health surface
- `agents/advisor/`

## Implementation guardrails

- No test may require live broker mutation or production trade submission.
- Production canary must be read-only with respect to positions, recommendations, intents, orders and fills; if decision persistence is tested in production, use an explicitly non-executable canary decision class and clean lifecycle rules.
- Prompt injection must never set deterministic trade delta, policy state, Critic state or risk result.
- Do not weaken assertions with broad skips/xfails or environment-specific waivers.
- Freeze/version behavioral decision contracts before using canary history for regression comparison.

## Done when

- [ ] Dedicated tests cover at minimum: 83→100 target math, explicit +17 delta, two-leg reallocation, mixed ST/LT trim, missing mark, stale mark, open-CC conflict, candidate outside universe, candidate without approved thesis, observe-only macro signal, Critic VETO/CHALLENGE/failure, risk REJECTED, context invalidation and LLM-render failure.
- [ ] Prompt-injection fixtures cannot alter any deterministic authoritative field.
- [ ] Same structured inputs produce the same actionability and trade-impact results across repeated runs.
- [ ] Production canary reports health and representative decision outcomes without changing trading state.
- [ ] Advisor health surface exposes actionable/review/research/blocked counts and failure reasons.
- [ ] Full suite and real GitHub Actions pass with no advisor-specific waiver.
- [ ] QA evaluation conducted: adversarial suite, canary dry run and full `pytest tests/ -v --tb=short` pass with no regressions introduced.
