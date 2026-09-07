# Fix Post-Expiration CC State-Transition Math for 30d/90d Horizons

- **ID:** 0106
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0105

## Problem

The `at_expiry`, `30d_post`, and `90d_post` CC horizons all evaluate `(min(S_t, K) - S_0 + premium) / S_0` using the stock price at whatever point in time `t` represents. This is wrong for the 30d/90d horizons when the option was assigned (S_exp > K): assignment happens at expiration and converts the position to cash; the stock price 30 or 90 days later is irrelevant. The current formula acts as though the investor held the stock through expiry and into the post-expiry window, when in fact they were assigned out at the strike price one month earlier. This makes CC performance analysis misleading for in-the-money assignments.

## Proposed approach

- At the `at_expiry` horizon, determine assignment state: if `S_exp > K`, the position is assigned and yields `(K - S_0 + premium) / S_0`; if `S_exp <= K`, the option expires worthless and the investor continues holding.
- Encode this as a `cc_state` enum (`assigned` / `expired`) stored alongside the `at_expiry` outcome row (can be a new column `cc_assignment_state TEXT` on `recommendation_outcomes`, or derived at query time from the stored prices).
- `30d_post` and `90d_post` branch on `cc_state`:
  - `assigned` → return is 0 (proceeds are cash; no additional price exposure). Optionally model reinvestment if a `replacement_ticker` is specified.
  - `expired` → investor still holds shares; return is `(S_t - S_exp) / S_exp` added to the `at_expiry` leg.
- Update `cc_strategy_return` and `cc_incremental_alpha` to respect the state transition.
- Update Dashboard JS rendering: post-expiry cells for assigned calls should display a note like "Assigned at expiry" rather than a raw stock return.

## Touches

- `agents/outcome_evaluator.py` — `_compute_returns()` CC branch, horizon loop
- `agent_db.py` — possible `cc_assignment_state` column migration on `recommendation_outcomes`
- `generate_dashboard.py` — post-expiry cell rendering
- `out/dashboard.html` — regenerate after dashboard change
- `tests/test_outcome_evaluator.py` — add tests for assigned vs. expired paths

## Done when

- [ ] Unit test (assigned path): S_exp > K → `at_expiry` = `(K-S0+prem)/S0`; `30d_post` and `90d_post` = 0 (cash, no further exposure).
- [ ] Unit test (expired path): S_exp <= K → `at_expiry` = `(S_exp-S0+prem)/S0`; `30d_post` uses S_30 relative to S_exp (continued hold).
- [ ] The two paths produce different `cc_strategy_return` values for the same set of prices — verified by test.
- [ ] Dashboard renders a clear label (e.g. "Assigned") in post-expiry cells when assignment state is true, rather than a misleading stock return percentage.
- [ ] `node --check` passes on regenerated `out/dashboard.html`.
- [ ] Full pytest suite passes with no regressions.
- [ ] Manual verification on optiplex: run the evaluator on a past SELL_CC recommendation with a known expiry; confirm the correct branch fires based on `S_exp` vs `K`.
