# Lot-Specific Tax Analysis for CC Assignment Decisions

- **ID:** 0155
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** 0151

## Problem

The current assignment tax gate in `assignment_eligible()` checks roughly: if near-zero LT lots exist and unrealized gain > $5,000, defer assignment. This is too coarse for real-money use.

Problems:
1. Any LT lot is treated as sufficient coverage. If 20 shares are LT and 80 are ST, assigning 100 shares delivers mostly ST shares -- but the current gate says "LT lot exists, it's fine."
2. $5,000 is a hard-coded gross-gain threshold with no connection to the actual tax cost. A $5,100 gain with minimal rate differential is fine; a $3,000 gain with a 22% ST/15% LT spread might not be.
3. There is no evaluation of days until affected ST lots become LT (i.e., should we roll 30 days to avoid ST treatment?).

## Proposed approach

Replace the coarse threshold check with a proper tax-friction analysis:

1. Call `agent_db.get_cost_lots(ticker)` to get lot-level data (acquisition date, cost basis, quantity)
2. Simulate which lots would be delivered (FIFO or specific ID, matching the broker's default)
3. For those lots, compute:
   - `st_gain` = gain on shares held < 365 days
   - `lt_gain` = gain on shares held >= 365 days
   - `incremental_tax_cost = st_gain * TAX_ST_RATE + lt_gain * TAX_LT_RATE`
   - `deferred_tax_if_roll_to_lt = st_gain * (TAX_ST_RATE - TAX_LT_RATE)` for lots within 90 days of LT crossover
4. Compute `days_to_lt_crossover` for the soonest ST lot
5. If `incremental_tax_cost > tax_friction_threshold` (configurable, suggest $500 default) AND `days_to_lt_crossover <= 90`: prefer ROLL_OUT to defer; add this to the reason string

The result feeds back into `assignment_eligible()` as a concrete dollar cost, not a hard veto -- it becomes one weighted input so the investor can see "assigning here costs ~$X in avoidable taxes."

## Touches

- `agents/covered_call_agent.py` -- `assignment_eligible()` tax block; new `_lot_tax_friction()` helper
- `agent_db.py` -- `get_cost_lots(ticker)` (may already exist; verify)
- `tests/test_covered_call_agent.py` -- lot-specific tax tests (20 LT / 80 ST scenario)

## Done when

- [x] Tax gate evaluates lot-level ST/LT split, not just existence of an LT lot
- [x] `days_to_lt_crossover` is computed per the soonest-to-mature ST lot
- [x] `incremental_tax_cost` in dollars is included in the assignment_eligible() reason/payload
- [x] Existing tests pass
