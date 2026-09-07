# Fix HOLD_CALL Outcome to Model Short-Call Terminal Payoff

- **ID:** 0126
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** 0125

## Problem

The HOLD_CALL outcome currently sets `actual_r = hold_r` (pure stock return from S_rec to S_exp) and `agent_r = hold_r − btc_mark / entry_price`. Both are wrong.

- `actual_r` ignores the short call the investor still holds. Holding the covered call to expiry produces: stock P&L `(S_exp − S_rec)` plus short-call P&L `(C_rec − max(0, S_exp − K))`. The combined incremental return from the management date is `(S_exp − S_rec + C_rec − max(0, S_exp − K)) / net_NAV`.
- `agent_r` models immediately closing the call at `btc_mark`, which is correct for a BUY_TO_CLOSE counterfactual — but the agent's recommendation was HOLD_CALL, so the agent path is simply the same covered-position outcome (agent and actual coincide because the recommendation was followed).

The correct model: `actual_r` = what actually happened (hold to expiry, including call payoff). `agent_r` = the counterfactual — what would have happened if the investor had BTC'd at the agent's implicit mark (`btc_mark`) instead of holding. So `agent_r = (btc_exec_counterfactual → stock held + call closed early) / net_NAV`.

## Proposed approach

- For `actual_r` at `at_expiry`: compute `(S_exp − S_rec + C_rec − max(0, S_exp − K)) / net_NAV`. Requires `K` (strike), `S_exp` (stock at expiry), `C_rec` (call mark at rec date), `net_NAV` from 0125.
- For post-expiry horizons: terminal state is locked at expiry (no additional incremental change), so `actual_r` stays equal to the `at_expiry` value.
- For `agent_r`: model BTC counterfactual as `(C_rec − btc_mark) / net_NAV` — the incremental gain/loss from buying back the call at the agent's mark vs. the call's current value. The stock return component cancels (both paths keep the stock during that window).
- All required values (`K`, expiry, `S_exp`) are already fetched or fetchable via `option_quote_snapshots` + price history.

## Touches

- `agents/outcome_evaluator.py` — `_compute_cc_management_returns()` HOLD_CALL branch
- `tests/test_outcome_evaluator.py` — update or add HOLD_CALL unit tests

## Done when

- [ ] HOLD_CALL `actual_r` at expiry = `(S_exp − S_rec + C_rec − max(0, S_exp − K)) / net_NAV`
- [ ] HOLD_CALL `actual_r` for post-expiry horizons locked at at-expiry value
- [ ] HOLD_CALL `agent_r` = `(C_rec − btc_mark) / net_NAV`
- [ ] Unit test for in-the-money expiry: K=150, S_exp=160, C_rec=2.00, btc_mark=1.50, S_rec=155, net_NAV=153 → verify numerics
- [ ] Unit test for out-of-the-money expiry: K=170, S_exp=160, C_rec=2.00 → short call expires worthless, full stock decline
