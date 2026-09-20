# Fix Regime Stress Directionality and Separate Inflation Level from Trend

- **ID:** 0488
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0477, 0487

## Problem

`compute_regime_stress()` uses absolute-value normalisation, so a 100bps yield *fall* produces the same rate_stress as a 100bps *rise*. The structural dimensions are directional: `rate_sensitivity` means hurt by *rising* rates, `dollar_sensitivity` means hurt by a *stronger* dollar. Stress from falling rates or a weakening dollar is not adverse — it can be favorable. Additionally, `inflation.direction` is named as a direction but is implemented as a level bucket (high/elevated/moderate/low), and the CPI variable in the regime engine has no trend component.

## Proposed approach

- Replace unsigned normalisation with signed stress scalars in range [-1, +1]: +1 = strongly adverse, 0 = neutral, -1 = strongly favorable.
  - Rate stress: positive when rates are rising (adverse for rate-sensitive names), negative when falling.
  - Dollar stress: positive when dollar is strengthening (adverse for dollar-sensitive names), negative when weakening.
- Rename `inflation.direction` → `inflation_level_regime` (high/elevated/moderate/low). Add `inflation_trend` computed from current CPI YoY vs the prior two FRED releases (rising/stable/falling).
- Keep geopolitical as `None` until a real signal source is identified; do not default to zero.
- Update `compute_regime_adjusted_risk()` to use signed interaction: positive result = structural exposure amplified by adverse regime; negative = structural exposure partially offset by favorable regime.
- Keep the "experimental — research only" label on all regime-adjusted outputs.

## Touches

- `portfolio_ai.py` — `compute_regime_stress()`, `compute_regime_adjusted_risk()`
- `macro_context.py` — `_compute_regime()`, inflation direction/trend split
- `generate_dashboard.py` — regime-adjusted risk display (signed values need updated colour scale)

## Done when

- [ ] Rising 10Y yield → positive rate_stress; falling yield → negative or zero rate_stress
- [ ] Strengthening dollar → positive dollar_stress; weakening → negative or zero
- [ ] `inflation_level_regime` and `inflation_trend` are separate fields
- [ ] `compute_regime_adjusted_risk()` returns signed interaction value
- [ ] Dashboard colour scale updated to handle negative (favorable) stress values
