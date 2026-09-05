# Build Portfolio Guardian Agent (Phase 3)

- **ID:** 0011
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005, 0006, 0007, 0008

## Problem

The system currently alerts on simple percentage moves (e.g., stock moved 8%) regardless of whether that move matters to the portfolio. A 1% position falling 10% is noise; a 12% position falling 4% is a real event. There is no volatility-normalized move detection, no layer-level portfolio impact analysis, and no structured "risk finding" that flows into a decision queue. Guardian makes the system proactively risk-aware rather than reactively headline-driven.

## Proposed approach

`agents/portfolio_guardian.py`

Deterministic checks run first (no LLM):
- **Layer drift**: `Drift_L = CurrentWeight_L - TargetWeight_L`; flag if |Drift| ≥ 5pp (already exists, promote to finding).
- **Position concentration**: `Weight_i = MarketValue_i / PortfolioValue`; flag if > `max_single_position_pct` from config.
- **Portfolio contribution**: `Impact_i = Weight_i × Return_i`; flag if |Impact| > 0.35% NAV.
- **Abnormal movement**: `Z_i = |r_i| / (HV20_i / √252)`; flag if Z > 2. This replaces simple % threshold — a calm stock moving 5% is a bigger signal than a volatile stock moving 5%.

LLM only runs for positions that crossed a materiality threshold. Input is structured, not a prose prompt.

LLM output:
```json
{
  "finding": "risk",
  "ticker": "XYZ",
  "severity": 72,
  "summary": "...",
  "why_now": "...",
  "portfolio_implication": "...",
  "suggested_action": "REVIEW",
  "no_action_case": "..."
}
```

`suggested_action` is always `REVIEW` — never `SELL` or `BUY`. The Guardian flags; the user decides.

HV20 data: check if already stored in DB from existing scoring pipeline; if not, calculate from `holding_day` price history.

## Touches

`agents/portfolio_guardian.py` (new), `portfolio_ai.py` (extract existing drift logic), `investment.db` (may need HV20 stored per holding), `agents/orchestrator.py`

## Done when

- [ ] All four deterministic checks run without LLM
- [ ] LLM only receives holdings that crossed at least one materiality threshold
- [ ] Z-score normalization uses HV20 from DB (or calculated from holding_day history)
- [ ] Finding severity is calculated deterministically (from Z, impact, drift magnitude) — LLM doesn't invent the number
- [ ] `suggested_action` is constrained to REVIEW in schema validation
- [ ] Finding persisted to `agent_findings` table
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced

