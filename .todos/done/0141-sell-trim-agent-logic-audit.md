# Sell/Trim Agent Logic Audit

- **ID:** 0141
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

The Sell/Trim agent's software architecture is sound: all five component scores are computed deterministically before any LLM call, DQ feedback is injected as context, and the action threshold ladder (NO_ACTION / HOLD / REVIEW / TRIM / EXIT) is clearly defined. No systematic review has been done of whether the scoring heuristics, thresholds, and weighting reflect sound investing principles.

Specific areas of concern:
- The 40% weight on thesis deterioration means broken thesis alone can push SellStrength to ~36 (EXIT requires 68), but a violated critical pillar only inflates T to ≥ 90 via soft inflation — there is no hard EXIT veto for a structurally broken investment case
- `_score_F()` uses flat additive scores regardless of deterioration magnitude (e.g., FCF negative → always +15, regardless of whether FCF is -$1M or -$1B)
- The TRIM fraction is fixed at 50% regardless of SellStrength magnitude — a score of 50 and a score of 67 both produce the same 50% reduction
- Tax lot status (ST vs LT) has no influence on whether the action is TRIM vs EXIT, even though assigning heavily-ST positions in a high-score scenario creates avoidable tax drag

## Proposed approach

Read `agents/sell_trim_agent.py` end-to-end and evaluate each scoring function against investing first principles:

1. **Weighting (40/20/15/15/10):** Is thesis-deterioration dominance correct? Does it underweight fundamentals for companies where thesis claims are qualitatively vague or hard to falsify?

2. **`_score_F()` fundamental deterioration (~lines 197-301):**
   - Revenue -5% YoY threshold — too sensitive for growth companies vs. mean-reverting businesses?
   - Flat-rate FCF → +15 regardless of magnitude — should severity matter?
   - 9-quarter lookback — enough for cyclical businesses? Does it distinguish structural decline from cyclical trough?
   - TTM revenue fallback (+20) when ≥ 8 quarters — interaction with the primary YoY signal

3. **`_score_V()` valuation percentile (~lines 328-583):**
   - Min 4 historical P/E data points for percentile computation — sufficient? What is the fallback quality?
   - Thesis `valuation_framework` fields (`attractive_threshold`, `fair_value_high`, `extreme_threshold`) — are these wired correctly and tested in practice?
   - Secondary 5-factor composite (0.30*H + 0.25*G + 0.20*FCF + 0.15*E + 0.10*C) — appropriate weights for a sell-signal context?

4. **`_score_O()` opportunity cost (~lines 615-642):**
   - `buffett_score` gap as the sole opportunity-cost metric — appropriate proxy? Should incremental expected return difference be used instead?
   - Top-5 from `candidate_universe` — are these ready-to-buy or just screened? Does the status filter ensure actionability?
   - Max score of 65 even for very large gaps (≥ 30) — is the 10% weight + 65 cap sufficient to surface strong reallocation opportunities?

5. **Critical override and TRIM vs EXIT:**
   - Critical pillar violated → `T = max(T, 90)`: gives SellStrength ≥ 36 minimum. Combined with average other scores can reach EXIT (≥ 68), but not guaranteed. Should a violated critical pillar be a hard EXIT trigger independent of composite score?
   - TRIM vs EXIT is purely score-driven (48-67 = TRIM, ≥ 68 = EXIT). Should tax lot composition (ST-heavy position near 365-day mark) shift a 65-score from EXIT to TRIM to preserve long-term status?
   - TRIM fraction is fixed at 50%: should it scale with SellStrength (e.g., 30% at score=48, 70% at score=67)?

Produce concrete backlog items for each gap found. This todo tracks the audit itself; each finding becomes its own todo.

## Touches

- `agents/sell_trim_agent.py` — `_score_F()`, `_score_V()`, `_score_O()`, `_score_T()`, `_score_P()`, `_action_from_strength()`, `_tax_note()` (audit, no edits here)
- `.todos/` — each finding produces a new backlog item
- `.todos/0137-agent-logic-audit.md` — mark Sell/Trim checkbox done when complete

## Done when

- [ ] All 5 scoring functions audited against investing first principles
- [ ] Critical override path (pillar violation → T inflation vs hard EXIT) evaluated with recommendation
- [ ] Tax lot TRIM vs EXIT differentiation evaluated with recommendation
- [ ] TRIM fraction scaling evaluated
- [ ] All findings captured as new backlog items
- [ ] `.todos/0137` Sell/Trim checkbox marked complete
