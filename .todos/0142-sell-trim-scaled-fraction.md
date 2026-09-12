# Scale TRIM Fraction with SellStrength

- **ID:** 0142
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

`action_payload["trim_fraction"]` is hardcoded at `0.5` for all TRIM recommendations (line ~885, `sell_trim_agent.py`). A SellStrength of 48 (just crossing the TRIM threshold) and a score of 67 (one point from EXIT) both produce the same 50% position reduction. This ignores the signal embedded in the score — a score of 67 indicates a much stronger case for reducing the position than a score of 48. Position sizing should reflect the conviction level.

## Proposed approach

Scale trim_fraction linearly within the TRIM band (48–67):
- ss = 48: trim_fraction = 0.25 (mild signal, small reduction)
- ss = 58: trim_fraction = 0.50 (moderate signal, standard trim)
- ss = 67: trim_fraction = 0.75 (near EXIT, aggressive reduction)

Formula: `trim_fraction = 0.25 + (ss - 48) / (68 - 48) * 0.50`
Clamp to [0.20, 0.75]. Round to nearest 0.05 for clean position math.

The LLM prompt should be updated to mention the scaled fraction so the rationale reflects it.

## Touches

- `agents/sell_trim_agent.py` — line ~885 `"trim_fraction": 0.5 if action == "TRIM" else None`
- LLM prompt builder — note scaled trim fraction in prompt context

## Done when

- [ ] ss=48 → trim_fraction ≈ 0.25; ss=67 → trim_fraction ≈ 0.75
- [ ] trim_fraction is still None for EXIT and HOLD/REVIEW
- [ ] Existing tests pass; spot-check a few scores against expected fractions
