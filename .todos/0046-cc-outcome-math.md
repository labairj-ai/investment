# Fix CC Outcome Math: Store Strategy Return and Incremental Alpha Separately

- **ID:** 0046
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

The CC outcome evaluator calculates something close to `premium_yield - upside_surrendered` when the stock finishes above strike. This is useful as incremental covered-call alpha versus holding, but it is not the total return of the CC strategy. Comparing this figure directly to SPY return is apples-to-oranges. The total CC return at expiration should be approximately `(min(S_T, K) - S_0 + premium) / S_0`. Without storing both figures, the outcome data conflates strategy-level performance with incremental-alpha measurement.

## Proposed approach

- Update the CC outcome calculation to store two separate fields:
  - `cc_strategy_return`: total return of the covered-call position at expiration `(min(S_T,K) - S_0 + premium) / S_0`
  - `cc_incremental_alpha`: CC path minus pure hold path `cc_strategy_return - hold_r`
- Add `dividends` as an optional adjustment to `cc_strategy_return` if dividend data is available.
- SPY comparison (`spy_r`) should be compared against `cc_strategy_return`, not the incremental alpha.
- Update any dashboard display that shows CC agent performance to use the correct field.

## Touches

- `agents/outcome_evaluator.py` (CC scenario branch in `_compute_scenarios`)
- `agent_db.py` (add `cc_strategy_return` / `cc_incremental_alpha` columns to outcome table, or store in `action_payload`)
- `generate_dashboard.py` or serve.py (any CC performance display)

## Done when

- [ ] CC outcome rows contain both `cc_strategy_return` and `cc_incremental_alpha`
- [ ] `cc_strategy_return` equals `(min(S_T, K) - entry + premium) / entry` for an above-strike expiry
- [ ] SPY comparison uses `cc_strategy_return` as the reference
- [ ] Dashboard CC performance section (if it exists) displays incremental alpha separately from strategy return
