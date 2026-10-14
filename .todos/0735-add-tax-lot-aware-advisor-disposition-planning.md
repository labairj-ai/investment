# Add Tax-Lot-Aware Advisor Disposition Planning

- **ID:** 0735
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0734

## Problem

The current Portfolio Advisor collapses each holding to average cost and labels tax status from the oldest lot. A mixed holding can therefore appear “LT” even when a proposed sale would include short-term lots.

Decision-grade sell/trim advice must evaluate the actual lots that could satisfy the proposed quantity.

## Proposed approach

- Add `agents/advisor/tax_lots.py` that consumes the exact captured cost lots and a simulated sell/trim quantity.
- Produce deterministic lot-selection scenarios such as FIFO, long-term-first and minimum-realized-gain, using existing `tax_utils` holding-period rules.
- Return selected lot IDs/quantities, ST gain/loss, LT gain/loss, gross realized gain/loss and any unsatisfied quantity.
- If configured tax-rate policy exists, optionally calculate estimated federal tax drag from that explicit policy. If no rate policy exists, do not invent tax dollars or call a heuristic “tax optimal.”
- Feed the structured lot analysis into later actionability/rendering stages.

## Touches

- `agents/advisor/tax_lots.py`
- `tax_utils.py`
- `agents/advisor/contracts.py`
- `portfolio_ai.py` when the old oldest-lot advisor shortcut is retired
- `tests/`

## Implementation guardrails

- Never classify an entire position ST/LT from one oldest/newest date when making a disposition recommendation.
- Lot quantities may be partially consumed, but total selected quantity must exactly equal the modeled sell quantity.
- Do not mutate `cost_lots` during preview.
- Do not claim the brokerage will honor a particular tax-lot disposition method unless a broker capability explicitly confirms it.
- State and local tax assumptions must not be fabricated.
- Tax analysis informs the decision but must not override thesis/risk blocks on its own.

## Done when

- [ ] Mixed ST/LT fixtures produce correct per-lot holding-period classification using canonical date utilities.
- [ ] A 40-share trim from 60 LT + 40 ST shares reports the actual selected-lot mix for each supported strategy rather than labeling all 40 shares from the oldest lot.
- [ ] Partial-lot selection reconciles exactly to requested shares and realized gain/loss math.
- [ ] When no configured tax rates exist, output contains ST/LT realized amounts but no invented tax-liability dollar estimate.
- [ ] Broker-lot-selection capability is represented separately from the planning recommendation.
- [ ] The old advisor prompt no longer relies on oldest-lot “Tax” as sufficient evidence for a sell/trim decision.
- [ ] QA evaluation conducted: tax-lot edge cases plus full `pytest tests/ -v --tb=short` pass with no regressions introduced.
