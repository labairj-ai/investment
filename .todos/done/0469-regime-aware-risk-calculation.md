# Replace Macro Health Composite with Exposure × Regime Stress

- **ID:** 0469
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0464, 0468

## Problem

The current "Macro Health" composite equally weights the four 1–10 exposure scores and maps them to health contributions regardless of the macro environment. This means high rate sensitivity always reduces the composite score even when rates are falling and stable, and high inflation-hedge score is always rewarded even when inflation is collapsing. The composite is better described as "Structural Macro Defensiveness" than "Current Macro Health" — it does not actually reflect whether the current environment is favorable or unfavorable for the holding. The geopolitical dimension has an additional directional problem: high geopolitical exposure is penalized uniformly even for defense contractors where escalation increases demand.

## Proposed approach

- Replace the composite formula with: `current_risk_per_dimension = structural_exposure × regime_stress` where both inputs come from 0464 (structural exposure) and 0468 (regime engine)
- `regime_stress` per dimension is a normalized scalar (0 = benign, 1 = severe) derived from the regime engine's raw observations — not invented by an LLM
- Portfolio composite = weighted sum of per-dimension current risk scores; display exposure and stress separately so both are visible
- Geopolitical dimension: store exposure as unsigned (sensitivity, not directional); let the regime engine carry a direction signal; combine as `geo_exposure × |geo_stress|` with direction displayed separately
- Rename "Macro Health" to something accurate: "Macro Risk Exposure" or "Macro Stress Score" — open question on final label
- During transition, keep the old composite in the DB under the original column name; add the new calculation in a new column so historical data is not destroyed

## Touches

- Macro composite calculation (dashboard generation and any risk engine consumer)
- Dashboard macro risk tab (display exposure and regime stress as distinct rows)
- DB schema (new composite column; old column preserved for history)
- Any Risk Engine gate that currently reads the Macro Health composite

## Done when

- [ ] Composite formula uses `exposure × regime_stress` per dimension rather than raw score health mapping
- [ ] High rate sensitivity does not penalize the composite during a falling-rate regime
- [ ] "Macro Health" label replaced throughout the dashboard and codebase
- [ ] Structural exposure and regime stress are displayed as separate values in the UI
- [ ] Old composite column preserved in DB under a legacy name; new column added alongside it
