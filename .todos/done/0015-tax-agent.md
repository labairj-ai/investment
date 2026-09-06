# Build Tax Agent (Phase 6)

- **ID:** 0015
- **Status:** done
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

## Outcome

- `agents/tax_agent.py`: New portfolio-scope agent. `_check_lt_crossover` finds lots within the 30–45 day LT window (per strategy config), checks missing basis (→ VETO, no LLM), computes days/gain/ST tax cost in Python, calls LLM for narrative with hardcoded fallback. `_check_tlh` finds worst ST loss lot per ticker, skips if YTD ST gains ≤ 0, computes TLH benefit and 30-day wash-sale window in Python, calls LLM for narrative. `_ytd_st_gains` includes both sell_transactions.st_gain and cc_positions net_premium income. LT date: `purchase + 365 days` (matching trigger engine).
- `config/strategy.json` + `strategy_config.py`: Added `TAX_ST_RATE = 0.37`.
- `agents/__init__.py`: Added tax_agent import.
- `agents/orchestrator.py`: Added "tax" to `_HOLDING_SCOPE_AGENTS`.
- QA (2026-09-05): TESTLT WAIT at 35 days, $1,500 gain, $555 ST cost — all from Python. TESTTLH HARVEST with $2,500 loss, $925 TLH benefit, wash-sale window flagged. VETO on zero-basis lot confirmed. TLH suppressed when no YTD ST gains confirmed. DB rows shown for run_id=14 (cleaned up after QA).
- Note for 0017 (Briefing refactor): tax agent produces `WAIT`, `HARVEST`, `VETO` actions. action_payload carries `days_to_lt`, `st_tax_cost`, `tlh_benefit`, `wash_sale_window_start/end` for the briefing agent to reference.

## Touches

`agents/tax_agent.py` (new), `cost_lots` table, `sell_transactions` table, `strategy_config.py` (ST tax rate), `agents/orchestrator.py`

## Done when

- [x] LT crossover trigger fires correctly for a lot 35 days from LT status
- [x] TLH opportunity trigger fires when unrealized loss > $500 with offsettable ST gains
- [x] All dollar amounts in recommendation come from Python, not LLM
- [x] Missing cost basis triggers VETO before LLM call
- [x] Wash sale 30-day window flagged in recommendation when applicable
- [x] `WAIT` recommendations include exact days until LT status
- [x] QA (backend): (a) Insert a test lot that is 35 days from LT crossover; confirm `WAIT` recommendation includes exact days and a dollar amount from Python (not LLM). (b) Insert a lot with unrealized loss > $500 and offsettable ST gains; confirm TLH recommendation fires and 30-day wash-sale window is flagged. Show DB recommendation rows before checking this box.

