# Build Deterministic Advisor Trade Impact Simulator

- **ID:** 0734
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0732, 0733

## Problem

The advisor currently instructs the LLM to calculate trade deltas, dollars and allocation effects. Prompt instructions reduce mistakes but do not make arithmetic authoritative or auditable.

Trade math must be deterministic and computed before the LLM writes a verdict.

## Proposed approach

- Add `agents/advisor/trade_impact.py` with a pure simulator that accepts an `AdvisorDecisionRequest` and captured `AdvisorDecisionContext`.
- Convert target-position requests to trade deltas from captured current shares.
- For each leg calculate reference price, delta shares, notional, before/after shares, before/after position value and weight, cash effect and layer-weight movement.
- For multi-leg reallocations calculate gross buys, gross sells and net cash requirement/proceeds using one captured price snapshot.
- Calculate CC eligibility before/after, contract-count change and any open-call share-coverage conflict.
- Surface concentration changes and invalid operations such as oversells or missing marks.

## Touches

- `agents/advisor/trade_impact.py`
- `agents/advisor/contracts.py`
- `strategy_config.py` only for canonical policy/target reads
- `tests/`

## Implementation guardrails

- No LLM calls and no database writes.
- Use only prices/share counts captured in the decision context; do not fetch a second price mid-simulation.
- Do not treat reference-price simulation as an executable limit price or fill guarantee.
- Preserve cash/NAV accounting identities within rounding tolerance; ignoring fees/slippage must be stated in structured assumptions.
- A sell may not exceed uncommitted/available shares; open CC coverage conflicts must be explicit, not silently netted away.
- Existing holdings, cost lots, CC rows, trade intents and broker state must remain unchanged.

## Done when

- [ ] A fixture holding 83 IGV shares with a 100-share target deterministically produces BUY 17.
- [ ] Before/after position weights and layer weights reconcile to the same captured NAV plus modeled cash movement.
- [ ] Two-leg reallocations report gross sell, gross buy and net cash consistently regardless of input-leg ordering.
- [ ] Crossing 99→100 shares reports one newly available standard CC contract; crossing 100→99 reports loss of eligibility.
- [ ] Selling shares covered by an open call produces an explicit conflict instead of an actionable result.
- [ ] Oversells, missing prices and contradictory targets fail closed with typed errors.
- [ ] Tests prove the simulator performs zero mutations to portfolio, recommendation, intent, order and fill tables.
- [ ] QA evaluation conducted: arithmetic/property-style fixtures plus full `pytest tests/ -v --tb=short` pass with no regressions introduced.
