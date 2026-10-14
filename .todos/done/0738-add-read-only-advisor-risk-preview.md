# Add Read-Only Advisor Risk Preview

- **ID:** 0738
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0734, 0736

## Problem

The trade engine has a strong pre-trade risk gate, but `risk_engine.evaluate()` persists decisions and assumes a real `TradeIntent`. The Portfolio Advisor needs the same risk logic before calling a recommendation actionable, without creating an intent or mutating execution state.

A decision preview must answer “would current policy permit this?” while remaining side-effect free.

## Proposed approach

- Refactor shared risk-rule computation into a pure evaluation core used by both existing persisted `evaluate()` and a new advisor `preview()` path.
- Build hypothetical equity intents from deterministic advisor trade legs using captured reference prices only for policy simulation.
- Return every rule check, decision, policy version/hash, account snapshot identity and explicit `preview_only=true`.
- For rules that cannot be meaningfully evaluated before a real order/limit price exists, return typed `UNKNOWN/SKIP` semantics and let advisor policy decide whether they block actionability or execution readiness.
- Keep the existing `evaluate()` persistence behavior and counterfactual recording unchanged.

## Touches

- `trade_engine/risk_engine.py`
- `agents/advisor/risk_preview.py`
- `agents/advisor/contracts.py`
- `tests/`

## Implementation guardrails

- Preview must create no `trade_intents`, `risk_decisions`, counterfactual rows, orders, fills, reservations or broker calls.
- Avoid maintaining a second copy of risk rules. The same underlying rule implementation must serve preview and persisted execution evaluation.
- Never substitute simulated/reference price for an actual execution limit-price assertion without labeling it.
- Policy version/hash and account snapshot used in preview must be captured for lineage.
- Existing fail-closed execution behavior must not weaken.

## Done when

- [x] For equivalent fixtures, preview and persisted evaluation return the same result for all rules that are evaluable in both modes.
- [x] Running preview leaves all trade/risk/order/fill row counts unchanged.
- [x] A position-limit failure, insufficient-cash failure and stale-risk-state failure all prevent advisor ACTIONABLE.
- [x] Admission-only or execution-only rules that cannot be evaluated are identified explicitly rather than silently passed.
- [x] Existing execution risk tests remain green and persisted `evaluate()` still writes exactly the expected audit rows.
- [x] QA evaluation conducted: parity/mutation tests plus full `pytest tests/ -v --tb=short` pass with no regressions introduced.

## Completion evidence

Completed 2026-10-14. Implementation and acceptance fixtures are documented in
`docs/advisor-decision.md`; focused advisor QA: 55 passed. Full local suite:
2,529 passed, 16 existing skips, no failures. Exact baseline and CC behavioral
contract gates passed. Read-only production-snapshot canary passed with trading
state unchanged and degraded evidence held in review. Real GitHub Actions passed:
https://github.com/labairj-ai/investment/actions/runs/38552153244
