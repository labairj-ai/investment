# Split Portfolio Advisor Explore And Decision Modes

- **ID:** 0740
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0736, 0737, 0738, 0739

## Problem

The current Portfolio Advisor is useful as a fast conversational tool, but its existing `/api/ai/chat` path should not be silently upgraded into a governed execution-style workflow. Users need to know whether they are brainstorming or receiving a decision-grade, policy-checked proposal.

The UI/API should make that boundary explicit.

## Proposed approach

- Preserve current `/api/ai/chat` semantics as Explore mode, with clear language that it is conversational analysis and not decision-authoritative.
- Add a separate Decision-mode endpoint, e.g. `POST /api/ai/decision`, that runs the governed pipeline: context → request parse → impact → tax → Critic → risk preview → actionability → persistence → rendering.
- Add an Explore/Decision selector in the Portfolio Advisor drawer and visually distinguish the modes.
- Render Decision-mode results from the structured decision object first, with the LLM responsible for explanation only.
- Display decision state, exact trade, portfolio/layer impact, tax-lot impact, thesis/candidate evidence, Critic verdict, risk preview, CC implications, invalidating conditions and expiry.
- Add a Convert to paper intent affordance only as disabled/future-facing or behind a separate explicit implementation gate; this TODO does not submit trades.

## Touches

- `serve.py`
- `generate_dashboard.py`
- `portfolio_ai.py`
- `agents/advisor/`
- `tests/`

## Implementation guardrails

- Explore mode remains available and does not inherit false ACTIONABLE labels.
- Decision mode must not stream a favorable verdict before deterministic gates finish.
- UI labels must not imply that ACTIONABLE means “will execute” or “broker approved.”
- No automatic conversion from Decision output to a paper/live intent.
- Existing chat history/session behavior should remain backward compatible unless explicitly migrated.
- Server errors or missing required decision evidence must fail closed and render a structured unavailable/review state.

## Done when

- [x] Portfolio Advisor visibly offers Explore and Decision modes with distinct descriptions.
- [x] Existing `/api/ai/chat` continues to work for Explore mode.
- [x] Decision endpoint returns a persisted `advisor_decision_id` plus structured decision payload and rendered explanation.
- [x] Decision rendering shows exact trade delta, before/after portfolio effects, tax-lot result, Critic, risk preview, CC implications, decision state, reasons and expiry/invalidation conditions.
- [x] A forced LLM rendering failure does not erase the structured decision; the UI can still display authoritative fields.
- [x] No Decision-mode request creates a trade intent, order or fill.
- [x] QA evaluation conducted: API/UI integration tests plus full `pytest tests/ -v --tb=short` pass with no regressions introduced.

## Completion evidence

Completed 2026-10-14. Implementation and acceptance fixtures are documented in
`docs/advisor-decision.md`; focused advisor QA: 55 passed. Full local suite:
2,529 passed, 16 existing skips, no failures. Exact baseline and CC behavioral
contract gates passed. Read-only production-snapshot canary passed with trading
state unchanged and degraded evidence held in review. Real GitHub Actions passed:
https://github.com/labairj-ai/investment/actions/runs/38552153244
