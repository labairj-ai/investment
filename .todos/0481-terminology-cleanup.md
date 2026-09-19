# Fix Ground-Truth Language in README and Inflation-Hedge Prompt Framing

- **ID:** 0481
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** none

## Problem

Two terminology problems remain. First, the README Weekly Macro Scorer section still calls the AI scores "the ground-truth baseline used by all downstream AI systems" — this was supposed to be corrected in 0472 but the phrase persists in the file. Describing model-estimated structural exposure scores as "ground truth" is inaccurate and potentially harmful if automated systems treat them as measured facts. Second, the scoring prompt header says "1=low risk, 10=high" for all four dimensions, but `inflation_hedge` is explicitly a benefit dimension where a high score is good, not a risk. Framing a benefit as a risk on the same 1=low/10=high scale is internally inconsistent and is likely to confuse the model into treating high inflation-hedge scores as a negative.

## Proposed approach

- **README fix**: Find and replace "ground-truth baseline used by all downstream AI systems" with "AI Structural Exposure Estimate v1 — model-estimated structural exposure used as context by downstream AI systems; not ground truth." Search for related phrases in case there are additional occurrences (e.g. "ground truth", "ground-truth").
- **Prompt header fix**: Change the scoring prompt dimension scale description from a single "1=low risk, 10=high" to dimension-specific framing:
  - Risk dimensions (rate_sensitivity, dollar_sensitivity, geopolitical_risk): `1=low exposure, 10=high exposure`
  - Benefit dimension (inflation_hedge): `1=low inflation protection, 10=strong inflation protection`
  - Either inline this in the prompt template or derive it from the `is_benefit` flag already present in `MACRO_DIMS`.
- Both changes are documentation/prompt text only — no logic changes.

## Touches

- `README.md` — Weekly Macro Scorer section
- `portfolio_ai.py` — scoring prompt template in `generate_holding_macro_scores()`

## Done when

- [x] `grep -r "ground.truth" README.md` returns no matches
- [x] README describes scores as "AI Structural Exposure Estimate v1 — model-estimated structural exposure... not ground truth"
- [x] Scoring prompt uses dimension-specific scale descriptions: risk dims say "1=low exposure, 10=high exposure"; inflation_hedge says "1=low inflation protection, 10=strong inflation protection"
