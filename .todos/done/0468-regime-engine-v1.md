# Build Transparent Multi-Horizon Macro Regime Engine

- **ID:** 0468
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0463

## Problem

The current macro context module derives regime interpretations from single-day ETF and index moves and maps them directly to causal narratives (GLD +1% → "strong inflation hedge demand", TLT +0.5% → "rates falling", curve >+50bp → "growth expected"). One-day moves in these instruments are too noisy to reliably signal regime and the causal labels are too strong — gold, for example, rises for at least six distinct reasons that the current code collapses into one. Feeding these interpretations into a scoring prompt or learning system embeds the noise and the causal assumption as if they were facts.

## Proposed approach

- Define five regime dimensions: rate, inflation, dollar, volatility, geopolitical
- For each, compute raw observations over multiple horizons (5-day, 21-day, 63-day) rather than a single day:
  - **Rate**: 10Y yield level, direction (slope of recent window), yield curve shape (10Y2Y, 10Y3M from 0463)
  - **Inflation**: CPI trend (month-over-month, year-over-year), TIPS breakeven direction (5Y, 10Y), PCE if available
  - **Dollar**: DXY or UUP return over 5/21/63-day windows
  - **Volatility**: VIX level, VIX percentile vs. trailing 252-day history, VIX direction
  - **Geopolitical**: placeholder — user-maintained ordinal or rules-based flag; do not invent from ETF moves
- Store raw observations separately from any regime classification label. Interpretation (e.g. "rising rate environment") is optional and clearly tagged as derived, not measured.
- Persist a `macro_regime_snapshots` table with one row per date, carrying all raw observations with provenance from 0463 (series_id, observation_date, retrieved_at per field).
- Open question: should regime classification (labels) be LLM-generated from the raw numbers, rules-based thresholds, or omitted entirely in V1?

## Touches

- `macro_context.py` (or equivalent macro fetch module)
- New `macro_regime_snapshots` table
- Dashboard macro risk rendering (replace one-day ETF move display with multi-horizon observations)
- Macro scoring prompt (receives regime object from this engine instead of ad-hoc fetches)

## Done when

- [ ] Regime observations are computed over at least 5-day and 21-day windows for rate, dollar, and volatility dimensions
- [ ] Raw observations are stored separately from any interpretation labels
- [ ] No single-day ETF return is used as a direct causal regime label
- [ ] Each stored regime snapshot carries per-field provenance (series_id, observation_date) per 0463 contract
