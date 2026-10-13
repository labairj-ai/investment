# Build Covered Call Volatility Surface and Term-Structure Model

- **ID:** 0693
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0690

## Problem

Current IV richness is largely contract IV relative to a historical-volatility forecast. That ignores whether a contract is rich or cheap relative to neighboring expirations, comparable deltas, skew, and known event variance.

This can make a longer-dated contract look attractive merely because its IV exceeds short-horizon realized volatility.

## Proposed approach

Construct a local option-volatility surface for each ticker from the same market snapshot used for candidate scoring.

Capture by expiry and delta/moneyness:

- ATM IV
- 20/25/30-delta call IV where available
- call skew relative to ATM
- IV term structure
- IV minus forecast realized volatility
- comparable-delta historical IV percentile when sufficient history exists
- earnings/event variance contribution

Derive:

- `vrp_estimate`
- `term_richness`
- `skew_richness`
- `event_premium`
- `surface_quality`
- `vol_surface_model_version`

Reject or flag stale, crossed, zero-bid, or obviously inconsistent surface points.

## Guardrails

- Do not extrapolate a complete surface from too few valid quotes.
- Missing surface data must reduce confidence, not fabricate richness.
- Preserve raw quote/IV inputs needed to reconstruct metrics.
- Event premium must not be treated as free alpha if the event itself is an avoid condition.

## Done when

- [ ] Candidate IV is compared with appropriate delta/DTE peers.
- [ ] Term richness is distinct from IV-vs-HV richness.
- [ ] Skew richness is distinct from term richness.
- [ ] Known event variance is explicitly identified.
- [ ] Synthetic flat, upward, inverted, and event-distorted surfaces are covered by tests.
- [ ] Stale/broken surface points are excluded or marked unusable.
- [ ] Surface/model version is persisted with candidate evidence.
