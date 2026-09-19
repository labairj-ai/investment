# Replace LLM Exposure Scores with Measurable Deterministic Factors

- **ID:** 0467
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0466

## Problem

All four macro exposure dimensions (rate sensitivity, inflation hedge, USD sensitivity, geopolitical) are currently numbers invented by the LLM with no quantitative grounding. The model is simultaneously the measurement instrument and the analyst — it has no access to the historical price data, financial statements, or supply-chain records that would let a human analyst derive the same numbers. Machine learning systems that consume these scores as features are therefore learning from model opinion, not from measured reality.

## Proposed approach

- For each dimension, identify the best available deterministic proxy:
  - **Rate sensitivity**: rolling regression of equity returns on 10Y yield changes (e.g. 52-week or 104-week window); net debt-to-equity as a secondary factor
  - **USD sensitivity**: rolling regression of equity returns on DXY or UUP changes; international revenue % as fundamental anchor
  - **Inflation hedge**: real-return beta (equity vs. TIPS or breakeven inflation); pricing-power proxy from gross-margin stability
  - **Geopolitical**: harder to determinize — start with geographic revenue concentration in high-risk countries; defense/government revenue share as a separate signal
- Each deterministic factor produces a raw value (not yet a 1–10 score). Normalize within the portfolio cross-section using percentile rank so scores remain comparable.
- LLM role shifts to: given these measured factors, explain in one sentence what they mean for this holding's macro risk.
- Implement incrementally — one dimension at a time. Each dimension where a deterministic factor is available should replace the LLM estimate in that dimension; LLM fallback only where no factor exists.
- Open question: store raw factor values alongside the normalized score so the Learning Lab can use either the raw factor or the score.

## Touches

- Macro scoring module
- Price history data pipeline (need yield, DXY returns aligned with equity returns)
- `company_financials` (foreign revenue, debt, gross margin)
- `holding_macro_scores` schema (add raw factor columns alongside normalized scores)

## Done when

- [ ] At least one dimension (rate sensitivity recommended first) uses a deterministic regression-based factor rather than a pure LLM estimate
- [ ] Raw factor value and normalization method are stored alongside the final score
- [ ] LLM is used only for explanation text, not as the source of the numeric score, for any implemented dimension
- [ ] Existing LLM-only scores are clearly labeled with `factor_method = 'llm_estimate'` to distinguish from deterministic replacements
