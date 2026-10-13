# Create Covered Call Decision Episode Ledger

- **ID:** 0700
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0690, 0691, 0692, 0693, 0694, 0695, 0696, 0697, 0698, 0699

## Problem

The system cannot evaluate whether the selected covered call was actually better than the alternatives unless the full candidate universe and prediction state are preserved at decision time.

Existing general decision episodes are oriented toward equity Opportunity Hunter decisions rather than option-contract selection.

## Proposed approach

Create immutable CC-specific decision episodes.

Persist one row per considered contract plus one decision-level record.

Candidate fields should include at minimum:

- ticker
- decision timestamp
- spot
- contract symbol/id
- strike
- expiration
- DTE
- OTM percentage
- bid/ask/mid
- expected fill
- premium and annualized yield
- delta/gamma/theta/vega
- IV and volatility-surface features
- HV/realized-vol forecast
- drift center/bounds
- terminal ITM probabilities
- terminal regret probabilities
- path/touch probabilities
- expected management cost
- expected execution cost
- expected tax cost
- cc_alpha and adjusted_cc_alpha
- duration/flexibility metrics
- regime state
- thesis/policy state
- overwrite fraction candidate
- eligibility
- rejection reason
- V2 score/rank
- V3 utility/rank
- selected flag
- scorer/model versions
- git SHA

Decision-level record should preserve NO_CALL as a real selected action when applicable.

## Guardrails

- Episodes are immutable after creation.
- Later quote/history refreshes cannot rewrite decision-time features.
- Rejected alternatives must be retained.
- Store enough provenance to reproduce every deterministic feature.

## Done when

- [ ] Every considered contract can be reconstructed from an episode.
- [ ] Rejected contracts and rejection reasons are retained.
- [ ] Selected contract or NO_CALL is explicit.
- [ ] V2 and V3 outputs are captured side by side.
- [ ] Model/scorer/config versions and git SHA are persisted.
- [ ] Episode immutability has direct tests.
- [ ] No production action depends on later mutation of an episode.
