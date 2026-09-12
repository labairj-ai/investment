# Scale _score_F() by Deterioration Magnitude

- **ID:** 0145
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

`_score_F()` in `sell_trim_agent.py` uses flat additive contributions regardless of deterioration magnitude:
- Revenue YoY < -5%: always +35 (same whether -5% or -40%)
- Gross margin < -3pp: always +30 (same whether -3.1pp or -15pp)  
- FCF negative: always +15 (same whether -$100K or -$5B)

This means a company with revenue down 5% and a company with revenue down 40% produce the same F score, even though the economic severity differs dramatically. Severe deterioration should produce a stronger signal.

## Proposed approach

Convert flat thresholds to severity-scaled contributions:

**Revenue decline:**
- -5% to -10%: +20
- -10% to -20%: +30
- > -20%: +40 (cap slightly above current to preserve dynamic range)

**Gross margin compression:**
- -3pp to -5pp: +20
- -5pp to -10pp: +30
- > -10pp: +40

**Free cash flow:**
- Negative and FCF/Revenue ratio > -0.05 (small burn): +10
- FCF/Revenue between -0.05 and -0.15: +20
- FCF/Revenue < -0.15 (heavy burn): +30

Keep the overall cap at 100. This preserves the spirit of the scoring (each metric contributes roughly proportionally to its weight) while making severe cases register stronger.

The TTM revenue fallback and analyst price-target checks can remain as-is (they are already somewhat severity-aware).

## Touches

- `agents/sell_trim_agent.py` — `_score_F()` (~lines 197-301): replace flat score additions with severity-scaled values
- `tests/` — update any test that asserts a specific F score for a given dataset

## Done when

- [ ] Revenue -5%: F contribution ~20; revenue -30%: F contribution ~40
- [ ] Gross margin -3pp: contribution ~20; -12pp: contribution ~40
- [ ] FCF lightly negative: +10; heavily negative: +30
- [ ] Existing tests updated and passing
