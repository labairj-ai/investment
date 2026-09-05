# Build Sell/Trim Agent (Phase 5)

- **ID:** 0019
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005, 0006, 0007, 0012, 0020

## Problem

Selling is a distinct discipline that requires different reasoning than detecting risk or monitoring a thesis. The Portfolio Guardian (0011) flags anomalies; this agent makes disposition recommendations. Without a dedicated sell agent, sell recommendations either don't exist or get generated casually as a side effect of other agents — which produces lower-quality sell reasoning and makes it impossible to analyze sell decision quality separately over time.

## Proposed approach

`agents/sell_trim_agent.py`

**Explicit prohibition**: price movement is a valid trigger but is never itself the sell reason. The agent must identify a specific dimension from the SellStrength formula as the primary rationale. A finding of "stock fell 8%" without an underlying cause is not a valid sell recommendation — the agent is not invoked unless a thesis, fundamental, valuation, portfolio, or opportunity condition also triggered.

**SellStrength formula (all deterministic components):**
`SellStrength = 0.40*T + 0.20*F + 0.15*V + 0.15*P + 0.10*O`

- **T — Thesis deterioration**: weighted sum of weakened/violated thesis claims from `thesis_claims` table (requires 0020). A single violated high-weight claim scores higher than two weakened low-weight claims.
- **F — Fundamental deterioration**: revenue growth, margins, FCF trend, balance sheet changes, estimate revisions vs. thesis thresholds from `company_financials` + `company_estimates`.
- **V — Valuation risk**: current multiple vs. historical range and analyst targets; extreme overvaluation (user-configured threshold in strategy_config).
- **P — Portfolio risk**: position weight vs. `max_comfortable_position` from thesis intake; layer over-concentration; correlation with other top holdings.
- **O — Opportunity cost**: is there a materially higher-scoring opportunity in the candidate universe that this capital would serve better?

**Tax treatment — separate calculation, not a thesis input:**
`NetDecisionValue = GrossDecisionValue - TaxFriction - TradingFriction`
TaxFriction calculated from actual tax lots (ST vs LT rate, lot-by-lot). A good company does not become good because selling is tax-efficient; a sell signal is not suppressed because selling is tax-inefficient. Tax affects the timing and mechanics recommendation, not the investment conclusion.

**Output actions (5 only):**
- `HOLD` — thesis intact, no material weakening
- `REVIEW` — something changed; insufficient evidence for action yet
- `TRIM` — reduce position size; thesis not necessarily broken (position sizing or valuation driven)
- `EXIT` — thesis no longer justifies ownership
- `NO_ACTION` — evaluation completed; nothing warrants action (stored with input hash per 0024)

**Rationale classes (required on every TRIM or EXIT):**
`THESIS_BREAK`, `FUNDAMENTAL_DETERIORATION`, `VALUATION`, `PORTFOLIO_CONCENTRATION`, `CAPITAL_REALLOCATION`, `RISK_CHANGE`, `TAX_STRATEGY`

**LLM role**: receives deterministic SellStrength scores per dimension + thesis claim statuses. Writes rationale and counter-case. Does not invent the scores. Output:
```json
{
  "action": "REVIEW",
  "sell_strength": 42,
  "primary_rationale": "FUNDAMENTAL_DETERIORATION",
  "summary": "...",
  "why_now": "...",
  "what_would_cause_exit": "...",
  "counter_case": "...",
  "tax_note": "...",
  "confidence": 89
}
```

## Touches

`agents/sell_trim_agent.py` (new), `portfolio_ai.py` (extract fundamental deterioration logic), `agents/orchestrator.py` (insert between Guardian and Critic), `agent_db.py` (rationale_class field on recommendations)

## Done when

- [ ] All 5 output actions implemented and schema-validated
- [ ] SellStrength calculated deterministically from T, F, V, P, O components before LLM call
- [ ] Tax calculation is separate from SellStrength — does not inflate or suppress the investment score
- [ ] TRIM and EXIT recommendations include a `primary_rationale` from the 7 rationale classes
- [ ] Price-as-reason is structurally impossible: agent is gated by trigger_type, not price move alone
- [ ] HOLD and NO_ACTION stored with input hash (per 0024 dedup logic)
- [ ] Rationale class stored on `recommendations` row for later outcome analysis
- [ ] QA (backend): Run the Sell/Trim agent for a holding with a known over-concentration (position > max_weight_pct). Confirm: (a) SellStrength computed deterministically before LLM call (log the components T, F, V, P, O), (b) tax calculation does not change the SellStrength value, (c) a TRIM or EXIT recommendation row written to DB with rationale_class set. Log the recommendation row before checking this box.

