# Prototype Exposure × Regime Stress as Experimental Parallel Metric

- **ID:** 0482
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0473, 0477, 0478

## Problem

The regime-adjusted risk calculation (`current_risk = structural_exposure × regime_stress`) from 0469 was never built because 0473 (correct beta units) and 0477 (correct regime units) need to land first. Once those are correct, the regime-adjusted metric should be introduced as a clearly-labelled experimental parallel — not as a replacement for the structural composite, and not as a trading or risk-engine input. Collapsing immediately into one opaque score would obscure whether regime adjustment actually adds information, since the interaction term could dominate or cancel signal in unpredictable ways.

## Proposed approach

- After 0473 and 0477 are complete, define a per-dimension `regime_stress` scalar (0 = benign, 1 = severe) derived from the regime engine's corrected observations. Start with simple linear normalisation over recent history for rate, dollar, and volatility; keep geopolitical as a manual placeholder.
- Compute `regime_adjusted_risk_per_dimension = structural_exposure_normalised × regime_stress` for each of the four dimensions.
- Display three separate values in the dashboard for each holding:
  1. **Structural exposure** (existing 0–100 composite, unchanged)
  2. **Regime stress** (per-dimension, from 0477)
  3. **Regime-adjusted current risk** (new experimental metric, clearly labelled "experimental — research only")
- Do not wire regime-adjusted risk into any recommendation logic, risk gates, or trade sizing.
- After ≥4 weeks of parallel data, compare: does regime-adjusted risk produce materially different portfolio rankings vs. structural exposure alone? Does it correlate with subsequent portfolio performance? Document findings before any promotion to non-experimental status.
- Open question: should regime stress be a portfolio-level scalar (same for all holdings) or a holding-specific product of regime × dimension exposure? The latter is more correct but requires the structural exposure to be already well-calibrated (depends on 0473/0476).

## Touches

- `portfolio_ai.py` or a new `macro_regime_risk.py` — regime stress normalisation and interaction calculation
- `generate_dashboard.py` — experimental metric display in Macro Risk tab
- `macro_regime_snapshots` table (already exists from 0468)

## Done when

- [x] Regime stress scalars (0–1) are computed per dimension from corrected regime engine (0477)
- [x] Regime-adjusted risk displayed in dashboard as "experimental — research only" alongside structural composite
- [x] Regime-adjusted metric is not used in any recommendation, sizing, or risk-gate logic
- [x] After 4 weeks of parallel data, a comparison note exists (even if just a comment) on whether ranking divergence is material
