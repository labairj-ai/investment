# Add Covered Call Equity-Upside and Regime Guard

- **ID:** 0697
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0694

## Problem

Covered calls mechanically surrender more upside when the stock rises. A call-writing model that ignores underlying equity regime can repeatedly cap strong compounders during favorable trends.

The objective is not to predict exact future prices, but to recognize when upside optionality is unusually valuable.

## Proposed approach

Create a deterministic equity-upside state from bounded inputs:

- 20/60/120-session momentum
- distance from 52-week high
- trend persistence
- recent breakout state
- known catalyst/event state
- thesis conviction
- thesis health
- portfolio concentration
- valuation/assignment target if available

Classify:

- `STRONG_UPTREND`
- `UPTREND`
- `NEUTRAL`
- `DOWNTREND`

Use this state only to adjust:

- overwrite fraction
- minimum OTM requirement
- maximum preferred delta
- utility hurdle / expected upside cost

Capture the raw features and classification version.

## Guardrails

- Regime state cannot independently force SELL_CC.
- Regime state cannot independently force NO_CALL unless explicit thesis policy says so.
- Bound every adjustment.
- Observe-only at first; no adaptive learned weights.

## Done when

- [ ] Strong-uptrend/high-conviction cases preserve more upside than neutral cases under otherwise identical economics.
- [ ] Regime adjustments are bounded and deterministic.
- [ ] Raw inputs and state version are persisted.
- [ ] Synthetic trend regimes are covered by tests.
- [ ] Feature can be disabled by configuration for champion/challenger comparison.
