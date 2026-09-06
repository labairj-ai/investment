# Upgrade Sell Valuation Model to Multi-Factor V Score

- **ID:** 0050
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

The Sell/Trim agent's V-score (`_score_V()`) — 15% of `SellStrength` — is based entirely on analyst consensus price target vs current price. Analyst targets are a lagging, anchored signal that should contribute at most 10–15% of valuation risk. The intended design is a multi-factor valuation score covering: valuation vs own history, growth-adjusted valuation, FCF valuation, earnings-estimate implied valuation, and analyst target as a minor corroborating signal. The current single-factor approach means a stock trading at 10× fair value but with a bullish analyst could show V=10.

## Proposed approach

Replace `_score_V()` with a weighted composite: `V = 0.30*H + 0.25*G + 0.20*FCF + 0.15*E + 0.10*C` where:
- **H** (history): forward P/E percentile vs own 5-year history (from `company_financials`)
- **G** (growth-adjusted): PEG or EV/growth relationship
- **FCF** (FCF valuation): FCF yield vs sector average or absolute threshold
- **E** (earnings estimates): forward EPS revision trend (up/flat/down)
- **C** (consensus target): analyst price target — current single-factor logic, now 10% weight

For each sub-factor, compute a 0–100 score; weight and sum. Fall back gracefully to available data — if only 2 factors have data, normalize to those 2.

## Touches

- `agents/sell_trim_agent.py` (`_score_V`)
- `agent_db.py` / `company_financials` table (P/E history, FCF, EPS revisions — verify available columns)

## Done when

- [ ] `_score_V()` computes a weighted composite of at least H, FCF, and C factors
- [ ] V-score is documented in `action_payload.component_notes.V` with per-factor breakdown
- [ ] Analyst target alone cannot push V above 35 (capped contribution)
- [ ] A stock at 90th percentile historical P/E produces V ≥ 70 even with bullish analyst target
- [ ] Falls back gracefully if historical P/E data unavailable (uses available factors, re-normalizes weights)
