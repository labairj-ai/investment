# Signed Interaction Contract Tests and Versioned Formula

- **ID:** 0491
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0488

## Problem

The signed regime interaction formula works correctly for rate and dollar dimensions but the inflation hedge sign convention needs explicit validation. High inflation hedge is a benefit (not a vulnerability), so the interaction with inflation stress must produce a favorable/mitigating (negative) result for high-hedge names — opposite to how rate/dollar dimensions work. Without an explicit unit test asserting all four semantic quadrants, the formula could silently treat inflation hedge as another risk dimension.

## Proposed approach

Add version constant `MACRO_INTERACTION_VERSION = "macro_interaction_v1"` to `portfolio_ai.py`. Store it in scored output alongside other schema versions.

Synthetic unit tests covering all four quadrants:
1. Rising rates + high rate_sensitivity (score=9) → adverse (positive interaction)
2. Falling rates + high rate_sensitivity → favorable (negative interaction)
3. High inflation + high inflation_hedge (score=9) → mitigating (negative interaction)
4. High inflation + low inflation_hedge (score=1) → little/no protection (near-zero or slightly adverse)
5. Unknown rate input + any sensitivity → None (not zero)
6. Unknown inflation input + any hedge → None (not zero)

The interaction formula for inflation_hedge must explicitly invert: `interaction = norm(hedge_score) × (-inflation_stress)` so that a strong hedge in a high-inflation regime produces a negative (favorable) number.

Also document the sign convention as a module-level docstring or comment block near `compute_regime_adjusted_risk()` so the convention survives future edits.

## Touches

- `portfolio_ai.py` — `compute_regime_adjusted_risk()`, `MACRO_INTERACTION_VERSION` constant
- `tests/test_regime_stress.py` — 6 new quadrant tests

## Done when

- [ ] `MACRO_INTERACTION_VERSION = "macro_interaction_v1"` constant defined and stored in scored output
- [ ] High inflation + high_hedge → negative (favorable) interaction value
- [ ] High inflation + low_hedge → near-zero or slightly adverse interaction value
- [ ] Rising rates + high rate_sensitivity → positive (adverse) interaction
- [ ] Unknown inputs → None, not zero
- [ ] Sign convention documented near `compute_regime_adjusted_risk()`
