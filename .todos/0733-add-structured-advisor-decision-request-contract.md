# Add Structured Advisor Decision Request Contract

- **ID:** 0733
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0732

## Problem

Decision questions arrive as natural language, but the current advisor lets the LLM both interpret the request and perform trade math in prose. That creates ambiguity between target position size and trade delta and makes multi-leg reallocations difficult to validate.

Decision mode needs a typed request contract before any calculations or recommendations occur.

## Proposed approach

- Add `AdvisorDecisionRequest` / `AdvisorTradeLegRequest` contracts under `agents/advisor/contracts.py`.
- Represent intent semantics explicitly: `TARGET_POSITION`, `TRADE_DELTA`, `REALLOCATE`, and `RESEARCH`.
- Each leg should carry normalized ticker, side/goal, quantity semantics, requested target or delta, funding relationship when present, and user constraints.
- Add a structured extraction path for natural-language requests using the existing structured LLM wrapper. Validate the result deterministically against the canonical context.
- Preserve the raw user text and parser/model/prompt version for later lineage.
- If material quantity/ticker semantics are genuinely unresolved, return a structured `needs_clarification` result rather than guessing.

## Touches

- `agents/advisor/contracts.py`
- `agents/advisor/request_parser.py`
- `ollama_client.py` only if existing structured-call support needs a narrow reusable helper
- `tests/`

## Implementation guardrails

- Parsing must not calculate shares-to-trade, taxes, risk, layer movement or actionability.
- The LLM may extract structure but may not invent a ticker, current position, price, share count or candidate membership.
- Normalize ticker aliases through the project's existing ticker normalization rules.
- Never convert “get X to 100 shares” into “buy 100 shares”; store target=100 and let the simulator derive delta later.
- Reject negative/impossible quantities and contradictory side/target combinations.
- No DB writes and no trade-engine calls in the parser.

## Done when

- [ ] “Get IGV to 100 shares” parses as a target-position request with target quantity 100, not a 100-share buy.
- [ ] “Buy 17 IGV” parses as a trade-delta request for +17 shares.
- [ ] “Sell 10 STZ and use it to get IGV to 100” parses as a linked multi-leg reallocation with one explicit sell leg and one target-position leg.
- [ ] Held/candidate ticker validation is deterministic and unknown symbols are surfaced explicitly.
- [ ] Ambiguous target-vs-delta requests return `needs_clarification` without a fabricated trade.
- [ ] Parser output includes raw request, parser version and model identity when an LLM was used.
- [ ] Adversarial prompt text cannot set actionability, risk status or Critic verdict fields because those fields do not exist in the request schema.
- [ ] QA evaluation conducted: table-driven parser tests plus full `pytest tests/ -v --tb=short` pass with no regressions introduced.
