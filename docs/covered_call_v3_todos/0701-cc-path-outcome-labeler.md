# Label Covered Call Path Outcomes and Probability Calibration

- **ID:** 0701
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0700

## Problem

Expiration P&L alone is insufficient to evaluate the predictions that matter for covered calls. The system needs to know whether predicted touch, roll, assignment, and management-risk probabilities were calibrated.

## Proposed approach

Forward-label each selected and scoreable CC episode using actual market path and trade-chain data.

Capture:

- maximum underlying price before expiry
- minimum underlying price
- maximum observed/reconstructed delta where possible
- strike touched
- regret barrier touched
- delta >= 0.30 event
- delta >= 0.50 event
- days to first touch
- days to first threshold event
- ever ITM
- rolled
- days to roll
- BTC
- assigned
- expired OTM
- number of roll hops
- total roll debit/credit
- total fees/slippage
- total option P&L
- CC strategy return
- hold return
- CC incremental alpha
- maximum forgone upside

Evaluate probability quality with:

- calibration buckets
- Brier score
- reliability error
- realized event frequency by predicted-probability band

Attribute roll-chain outcomes back to the originating SELL_CC `trade_chain_id`.

## Guardrails

- Do not label future information into decision-time feature columns.
- Distinguish observed from reconstructed values.
- Open/incomplete chains remain censored rather than forced into a terminal label.
- Minimum sample size rules must be explicit.

## Done when

- [ ] Strike-touch predictions can be compared with realized strike touches.
- [ ] Delta-threshold predictions can be compared with realized/reconstructed events.
- [ ] Roll-risk predictions can be calibrated against actual roll frequency.
- [ ] Brier score and calibration tables are queryable.
- [ ] Recursive roll-chain economics map back to the originating SELL_CC episode.
- [ ] Censored/open positions are handled explicitly.
- [ ] Labels never mutate original decision-time features.
