# Make Episode Eligibility Horizon-Exact for sessions_v2

- **ID:** 0389
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** none

## Problem

`compute_data_health()` determines episode eligibility using `eligible_cutoff_ts = now - 91 calendar days` for both `calendar_v1` and `sessions_v2` horizons. The canonical target (`sessions_v2`) defines maturity as 63 NYSE trading sessions, not 91 calendar days. These values are close but diverge around holidays and long weekends. The function that decides whether a label *should exist* is using a different horizon definition than the function that *produces* the label, which can cause false "coverage looks ok" or false "not enough data" signals.

## Proposed approach

- Use the same market-calendar function the outcome labeler uses to determine exchange sessions. If a trading-session calendar is already available in the codebase, reuse it; otherwise use a simple NYSE holiday list or `pandas_market_calendars`.
- `compute_data_health(conn, target_horizon_version)`:
  - `calendar_v1`: `eligible_cutoff_ts = now - 91 * 86400` (unchanged)
  - `sessions_v2`: `eligible_cutoff_ts` = timestamp of the date that was 63 NYSE sessions ago
- Use the same eligibility cutoff for per-version coverage queries.
- Open question: is a market-session calendar library already used by the outcome labeler, or would this introduce a new dependency?

## Touches

- `agents/learning/calibration.py` — `compute_data_health()`
- Wherever market-session counting is already done (outcome labeler, if it exists)
- `tests/test_calibration.py` — `TestDataHealthV20380`

## Done when

- [ ] `eligible_episodes` for `sessions_v2` target uses 63 exchange sessions, not 91 calendar days
- [ ] Coverage queries for `sessions_v2` use the same cutoff
- [ ] `calendar_v1` path unchanged
- [ ] Test demonstrates the two horizons produce different eligible_episode counts around a holiday cluster
- [ ] Full test suite passes
