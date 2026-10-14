# Enforce Advisor Actionability and Evidence Authority

- **ID:** 0736
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0732, 0734, 0735

## Problem

The current advisor can emit “Recommended” directly from LLM prose even when required data are degraded or when observe-only evidence is present. This creates a side door around the project's existing promotion, freshness and decision-governance contracts.

Actionability must be a deterministic policy outcome, not an LLM opinion.

## Proposed approach

- Add a versioned `ADVISOR_POLICY_VERSION` and deterministic policy function under `agents/advisor/policy.py`.
- Use the states `ACTIONABLE`, `REVIEW_REQUIRED`, `RESEARCH_ONLY`, and `BLOCKED`.
- Treat required/advisory/experimental source authority consistently with canonical capability/freshness state.
- A new-position BUY/ADD may be `ACTIONABLE` only when the ticker is in the canonical candidate universe and has an active/approved thesis under existing thesis-intake semantics; otherwise it is `RESEARCH_ONLY`.
- Missing Critic or risk-preview evidence should initially resolve to `REVIEW_REQUIRED`; later TODOs will satisfy those gates.
- Fail closed for invalid trade math, oversells, unresolved open-call coverage conflicts, critical required-source failures and explicitly vetoing thesis state.
- Preserve an explicit distinction between decision actionability and execution readiness.

## Touches

- `agents/advisor/policy.py`
- `agents/advisor/contracts.py`
- `portfolio_ai.py`
- `tests/`

## Implementation guardrails

- The LLM cannot set, raise or override `decision_state`.
- Sources marked ADVISORY/EXPERIMENTAL/observe-only may be displayed as context but may not change ranking, sizing or actionability unless their existing production-promotion state authorizes influence.
- In particular, current macro scores/learning outputs with production influence zero must not become an implicit verdict/sizing input through the advisor prompt.
- Do not require an existing agent recommendation for every advisor-originated proposal; however, advisor `ACTIONABLE` means “decision-grade for user review,” never “approved for automatic execution.”
- No automatic trade-intent creation or broker action.
- Policy decisions must include machine-readable reasons and policy version.

## Done when

- [ ] Identical structured evidence always produces the same decision state independent of LLM narrative.
- [ ] Required stale/error inputs downgrade or block actionability with explicit reasons.
- [ ] Observe-only macro evidence can change rendered context but cannot change deterministic state, trade size or candidate rank in tests.
- [ ] A new BUY with no active approved thesis is `RESEARCH_ONLY`.
- [ ] An otherwise valid governed sell/trim can progress without requiring a pre-existing recommendation row.
- [ ] Unresolved open-call coverage conflict is never `ACTIONABLE`.
- [ ] Missing future Critic/risk evidence yields `REVIEW_REQUIRED`, proving fail-closed composition.
- [ ] QA evaluation conducted: policy truth-table tests plus full `pytest tests/ -v --tb=short` pass with no regressions introduced.
