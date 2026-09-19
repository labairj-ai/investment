# Fix Regime Engine Units and Add Missing Dimensions with Provenance

- **ID:** 0477
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0463, 0468

## Problem

The current regime engine contains a unit error: `_chg_bps()` multiplies raw VIX level changes by 100, so a VIX move from 18 → 20 is recorded as 200 rather than +2.0 points or +11.1%. This makes the `vix_5d_chg` field meaningless for any consumer that interprets it as a basis-point or percentage value. The regime object is also missing several dimensions needed to characterise the macro environment: explicit curve state from the two correct series (10Y–2Y and 10Y–3M from 0463), inflation direction and multi-month trend (not just CPI level), directional labels for rate and dollar moves, geopolitical/trade stress, and per-field source/observation provenance. Causal interpretations (e.g. "rates rising") are currently embedded in the raw data structure; they should be separated.

## Proposed approach

- Fix VIX units: rename `vix_5d_chg` to `vix_5d_change_points` (raw level delta, e.g. +2.0) and add `vix_5d_change_pct` (percentage change). Remove the `* 100` multiplier in `_chg_bps()` or replace with correctly named helpers.
- Apply the same unit discipline to rate change fields: `yield_10y_5d_chg_bps` (already likely in bps — verify), `yield_10y_21d_chg_bps`, etc. Confirm each field's units match its name.
- Add missing regime dimensions:
  - **Curve state**: `curve_10y2y_bps` and `curve_10y3m_bps` pulled from `yield_curve_10y2y_bps` / `yield_curve_10y3m_bps` (0463)
  - **Inflation direction**: multi-month CPI change (e.g. 3-month annualised change from FRED CPIAUCSL), not just current YoY level
  - **Dollar directional state**: `dollar_direction` derived from 21-day UUP return sign and magnitude thresholds
  - **Rate directional state**: `rate_direction` from 21-day 10Y change sign
  - **Geopolitical/trade stress**: placeholder field `geo_stress_manual` with a documented update cadence; do not fabricate from ETF moves
- Add per-field provenance inside the regime dict: each sub-dict should carry `source`, `observation_date`, and `units`.
- Move all causal interpretation strings (e.g. "rates rising — pressure on long-duration assets") to a separate `regime_interpretations` sub-dict, keeping the raw `regime` object free of narrative.

## Touches

- `macro_context.py` — `_compute_regime()`, `_chg_bps()`, `fetch()`
- `macro_regime_snapshots` table (via `portfolio_ai.py` if regime is persisted there)

## Done when

- [x] VIX 5d change is recorded in named units (points and/or percent), not ×100 of raw delta
- [x] `yield_curve_10y2y_bps` and `yield_curve_10y3m_bps` appear in the regime object
- [x] Inflation direction (multi-month trend) present alongside CPI level
- [x] Each regime sub-dict carries `source`, `observation_date`, `units`
- [x] Causal interpretation strings are in a separate `regime_interpretations` sub-dict, not mixed into the raw values
