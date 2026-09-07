# SELL_CC Full Dependency Set

- **ID:** 0090
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0086, 0087, 0088

## Problem

A newly generated SELL_CC recommendation only carries PRICE and MACRO_STATE dependencies. If IV collapses from 48% to 30% the day after recommendation, or spread widens, or an earnings date moves inside the contract window, the recommendation remains open. These are exactly the conditions that would make the call unattractive. Without the right dependency set, SELL_CC recommendations never self-expire on changed option market conditions.

## Proposed approach

When the CC agent generates a `SELL_CC` recommendation, emit these additional dependencies (with contract-identifying metadata in `dependency_metadata_json` per 0086):

- `OPTION_IV` — snapshot IV at recommendation time; threshold e.g. 0.20 (20% relative change). Metadata: `{strike, expiration, threshold}`
- `OPTION_LIQUIDITY` — snapshot spread_pct at recommendation time; threshold e.g. 0.15. Metadata: `{strike, expiration, threshold}`
- `OPTION_EXPIRATION` — the contract expiration date. Fires when within 5 calendar days.
- `EARNINGS_DATE` — earnings date at recommendation time. Fires when earnings moves inside expiration.
- `THESIS_VERSION` — thesis version hash, already used elsewhere.
- `CC_POSITION_STATE` — boolean: does an open CC already exist for this ticker? Fires when state changes (position opened/closed externally). Use dependency_key = ticker, original_value = "open"/"none".

In `covered_call_agent.py`, extend the `deps` list assembled before `Recommendation(dependencies=deps)` to include the above. Each dep dict should include a `"metadata"` key with the contract-specific fields for 0086 to persist.

## Touches

- `agents/covered_call_agent.py` — extend `deps` list with 5 new dependency dicts
- `agents/dependency_checker.py` — add `_check_cc_position_state()` for CC_POSITION_STATE type; map it in `_KNOWN_DEPENDENCY_TYPES`
- `agent_db.py` — `get_open_cc_for_ticker()` helper (may already exist in `covered_call_rec.py`)
- `tests/test_lifecycle.py` — add scenario: SELL_CC rec with IV dependency fires when IV stored snapshot diverges

## Done when

- [ ] A generated SELL_CC recommendation has ≥ 5 dependency types (PRICE, OPTION_IV, OPTION_LIQUIDITY, OPTION_EXPIRATION, EARNINGS_DATE, THESIS_VERSION, CC_POSITION_STATE)
- [ ] Each option-related dep carries strike + expiration in `dependency_metadata_json`
- [ ] `_check_cc_position_state()` returns supersession when CC position state has changed
- [ ] Test verifies new dependency set is written to DB on CC recommendation creation
