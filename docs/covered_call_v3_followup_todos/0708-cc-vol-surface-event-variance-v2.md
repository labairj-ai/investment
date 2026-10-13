# Refine Covered Call Volatility Surface and Event Variance Model

- **ID:** 0708
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0693, 0707

## Problem

The current local volatility model is a useful V1 but remains coarse in two areas:

1. `term_richness` is primarily anchored to 25-delta IV across nearby expirations rather than interpolating expected IV at the candidate's own delta and maturity.
2. Earnings/event variance currently approximates incremental event variance using later-maturity DTE for both terms, rather than comparing total implied variance across maturities.

This can distort event-premium and term-richness estimates.

## Proposed approach

### Candidate-specific surface interpolation

For each valid candidate, estimate expected IV at:

- candidate delta
- candidate DTE

using local interpolation from observed option-chain points.

Prefer simple, auditable interpolation:

- linear interpolation within same-expiry delta support;
- interpolate total variance across expirations when both neighboring maturities exist;
- no unsupported extrapolation.

Compute:

- `surface_expected_iv`
- `candidate_surface_residual`
- `candidate_surface_residual_pct`
- `surface_interpolation_quality`

Keep existing 20/25/30-delta diagnostics.

### Event variance

Use total implied variance:

`total_variance = IV^2 * T`

Estimate incremental event variance from neighboring expiries that bracket the event where possible:

`event_variance ≈ max(0, TV_after - interpolated_non_event_TV_after)`

When only a shorter pre-event expiry is available, use conservative bounded assumptions and mark quality accordingly.

Derive:

- `event_variance_estimate_v2`
- `event_vol_contribution`
- `event_premium_estimate_v2`
- `event_variance_quality`

## Guardrails

- Do not fit a complex spline/SVI model without sufficient data and tests.
- No extrapolation beyond observed delta range.
- No event-premium estimate when event date placement relative to expiries is unknown.
- Event premium does not automatically count as positive alpha; event policy still controls eligibility.
- Surface errors must reduce confidence rather than fabricate values.
- Persist raw surface points/reference inputs used in interpolation.

## Acceptance tests

### Candidate interpolation
- [ ] Flat synthetic surface => near-zero residual for all candidates.
- [ ] Linear skew synthetic surface => residual near zero at supported candidate deltas.
- [ ] Candidate outside observed delta support => no interpolated IV / insufficient quality.
- [ ] Interpolation across two maturities uses total variance, not raw IV arithmetic.

### Event variance
- [ ] No-event flat term structure => event variance ~0.
- [ ] Known earnings between two expiries with higher post-event total variance => positive event variance.
- [ ] Formula uses `IV1^2*T1` and `IV2^2*T2`.
- [ ] Missing event date => event variance unavailable.
- [ ] Only one usable expiry => insufficient quality or explicitly conservative fallback.
- [ ] Negative inferred event variance floors to zero but diagnostic raw value is retained if useful.

### Outliers/data quality
- [ ] Crossed quote excluded.
- [ ] Zero-bid candidate excluded from calibrated surface if policy requires.
- [ ] Extreme isolated IV outlier is flagged/excluded.
- [ ] Stale quote excluded.
- [ ] Candidate residual cannot be computed from stale peers.

## QA requirements

### Backend QA
- [ ] Run side-by-side V1 vs V2 surface metrics for current holdings.
- [ ] Spot-check at least five live chains across different DTEs.
- [ ] Verify no current production selection changes while V3 is observe-only.
- [ ] Persist both old and new metric versions during comparison period if needed.

### Dashboard QA
- [ ] Learning Lab exposes candidate IV vs expected surface IV.
- [ ] Event variance quality/source is visible.
- [ ] Missing/insufficient estimates display explicitly rather than as zero.

### Promotion guard
- [ ] If V3 model version changes due to this TODO, prospective promotion cohort restarts under the new model version.
