# ALLOW_ASSIGNMENT Must Branch on Actual Expiry Price

- **ID:** 0127
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** 0125

## Problem

`ALLOW_ASSIGNMENT` currently always calculates the return as if shares were called away at the strike (`(K − S_rec) / net_NAV`), but that is only correct when `S_exp > K` at expiry. If the stock falls below the strike before expiration the short call expires worthless (OTM), no assignment occurs, and the investor keeps the shares at `S_exp`. The current code produces a meaningless result (possibly negative) when the stock is below the strike at expiry — it treats an OTM expiry as an assignment that never happened.

## Proposed approach

Branch on `S_exp` vs. `K` at the `at_expiry` horizon:

- **Assigned path** (`S_exp > K`): shares called away at strike. `actual_r = (K − S_rec + C_rec) / net_NAV`. The `C_rec` term appears because holding the short call to assignment means the investor collected the remaining time value by not buying back early.
- **OTM expiry path** (`S_exp <= K`): option expires worthless, investor keeps shares. `actual_r = (S_exp − S_rec + C_rec) / net_NAV` — stock return plus full option value retained.

Post-expiry horizons (30d_post, 90d_post) lock at the at-expiry value in both branches (shares were sold in the assigned path; for OTM the stock return from expiry forward is a separate, unevaluated equity position).

The `agent_r` (what the agent's recommendation path would yield) mirrors the actual path since the investor followed the ALLOW_ASSIGNMENT rec.

## Touches

- `agents/outcome_evaluator.py` — `_compute_cc_management_returns()` ALLOW_ASSIGNMENT branch
- `tests/test_outcome_evaluator.py` — add OTM expiry test case

## Done when

- [ ] ALLOW_ASSIGNMENT at_expiry branches on `S_exp > K` (assigned) vs `S_exp <= K` (OTM expiry)
- [ ] Assigned path: `actual_r = (K − S_rec + C_rec) / net_NAV`
- [ ] OTM expiry path: `actual_r = (S_exp − S_rec + C_rec) / net_NAV`
- [ ] Post-expiry horizons lock at at-expiry value in both branches
- [ ] Unit test for assigned case: K=150, S_exp=158, C_rec=2.00, S_rec=152, net_NAV=150 → `(150 − 152 + 2) / 150 = 0.0`
- [ ] Unit test for OTM case: K=150, S_exp=142, C_rec=2.00, S_rec=152, net_NAV=150 → `(142 − 152 + 2) / 150 = −0.0533...`
