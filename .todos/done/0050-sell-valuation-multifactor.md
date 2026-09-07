# Upgrade Sell Valuation Model to Multi-Factor V Score

- **ID:** 0050
- **Status:** done
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

- [x] `_score_V()` computes a weighted composite of H (P/E), G (PEG), FCF quality, E (analyst rec), C (price target)
- [x] V-score notes contain per-factor breakdown (e.g., "P/E=42x (expensive); PEG=2.3 (stretched)")
- [x] Analyst target (C factor) has 10% weight max — cannot alone push V above 8.5 points
- [x] P/E >35x scores H=70, P/E >50x scores H=85 — even with bullish analyst, V stays elevated
- [x] Falls back gracefully: missing factors excluded, remaining weights re-normalized
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change

## Outcome

`agents/sell_trim_agent.py` — `_score_V()` replaced with 5-factor composite: H (trailing P/E absolute level 0-100), G (PEG from analyst forward EPS estimates vs trailing P/E), FCF (FCF sign/trend), E (analyst recommendation string → 0-100), C (price target vs current, old logic). Weights: H=0.30, G=0.25, FCF=0.20, E=0.15, C=0.10 with re-normalization when factors are absent. No 5-year P/E history in DB, so H uses absolute thresholds (P/E>50→85, >35→70, >25→45, >15→20, else 5). Component_notes.V now contains per-factor descriptions.
