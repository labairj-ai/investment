# Build Tax Agent (Phase 6)

- **ID:** 0015
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005, 0006, 0007

## Problem

The system has rich tax infrastructure (cost_lots, sell_transactions, CC premium income, ST/LT netting, FIFO calculations, TLH logic in the dashboard) but it is entirely reactive — the user must open a tool and query it. The Tax Agent makes it proactive: it surfaces "GRMN lot reaches LT status in 42 days — avoid realizing gains before then" or "XYZ has a $4,200 loss that can offset current-year ST gains" without the user having to remember to check.

## Proposed approach

`agents/tax_agent.py`

Triggered by (from trigger engine):
- Any lot within 30–45 days of LT crossover date
- Unrealized loss > $500 appearing on a holding with offsettable realized ST gains in current year
- Large realized ST gain event (sale or CC assignment) creating new offset opportunities

**Deterministic calculations (no LLM):**
- LT crossover date per lot: `acquired_date + 366 days`
- Days until LT: `crossover_date - today`
- Unrealized loss: `(current_price - cost_basis) * shares`
- Current-year realized ST gains: query `sell_transactions` + CC income
- Net benefit of TLH: `unrealized_loss * estimated_st_rate` (use rate from strategy_config)
- Wash sale window: `crossover ± 30 days` — flag if a replacement purchase would trigger wash sale

**LLM role** (narrow):
Receives the Python-calculated figures and writes a plain-language action summary. Does not produce dollar amounts (Python provides those). Answers: "Given these numbers, what is the clearest action and what is the risk of acting vs. not acting?"

Output:
```json
{
  "action": "WAIT",
  "ticker": "GRMN",
  "lot_id": "...",
  "summary": "...",
  "action_risk": "...",
  "no_action_case": "..."
}
```

Actions: `WAIT` (LT timing), `HARVEST` (TLH opportunity), `REVIEW` (complex situation).

Missing cost basis → VETO (handled by Critic deterministic gate in 0012).

## Touches

`agents/tax_agent.py` (new), `cost_lots` table, `sell_transactions` table, `strategy_config.py` (ST tax rate), `agents/orchestrator.py`

## Done when

- [ ] LT crossover trigger fires correctly for a lot 35 days from LT status
- [ ] TLH opportunity trigger fires when unrealized loss > $500 with offsettable ST gains
- [ ] All dollar amounts in recommendation come from Python, not LLM
- [ ] Missing cost basis triggers VETO before LLM call
- [ ] Wash sale 30-day window flagged in recommendation when applicable
- [ ] `WAIT` recommendations include exact days until LT status
- [ ] QA (backend): (a) Insert a test lot that is 35 days from LT crossover; confirm `WAIT` recommendation includes exact days and a dollar amount from Python (not LLM). (b) Insert a lot with unrealized loss > $500 and offsettable ST gains; confirm TLH recommendation fires and 30-day wash-sale window is flagged. Show DB recommendation rows before checking this box.

