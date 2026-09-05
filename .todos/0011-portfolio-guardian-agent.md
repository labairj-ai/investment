# Build Portfolio Guardian Agent (Phase 3)

- **ID:** 0011
- **Status:** done
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

- [x] All four deterministic checks run without LLM
- [x] LLM only receives holdings that crossed at least one materiality threshold
- [x] Z-score normalization uses HV20 from DB (or calculated from holding_day history)
- [x] Finding severity is calculated deterministically (from Z, impact, drift magnitude) — LLM doesn't invent the number
- [x] `suggested_action` is constrained to REVIEW in schema validation
- [x] Finding persisted to `agent_findings` table
- [x] QA (backend): Run the Guardian agent against real portfolio data and confirm: (a) all 4 deterministic checks ran without LLM call for calm positions, (b) a finding row appears in `agent_findings` for any holding that crossed a threshold, (c) severity was calculated deterministically (not assigned by LLM). Log the finding row content before checking this box.

## Outcome

New file: `agents/portfolio_guardian.py`. Registered in `agents/__init__.py`.

**4 deterministic checks implemented:**
1. Layer drift — compares `layer_day.weight_pct` vs `LAYER_TARGETS` via `_LABEL_TO_INT` reverse map (layer_day stores full label strings, not ints)
2. Position concentration — `weight_pct > HOLDING_GROSS_DOM (25%)`
3. NAV contribution — `weight_pct * |change_pct| / 100 > 0.35pp`
4. Z-score — `|change_pct/100| / (HV20/√252) ≥ 2.0`; HV20 computed from last 20 `holding_day.change_pct` rows

LLM only fires for positions with impact or Z-score triggers; validates `suggested_action == "REVIEW"` before accepting output. Layer drift and concentration-only findings are deterministic-only.

**Bug caught during QA:** `layer_day.layer` stores full label strings ("Layer 1: L1 Structural Ballast"), not integers. Added `_LABEL_TO_INT` reverse map from `LAYER_LABELS` to fix target lookup.

**QA finding rows logged (2026-09-05, calm day):**
- id=2: `layer_drift`, ticker=null, severity=71, confidence=90 — "L1 Structural Ballast: overweight by 5.2pp (38.2% actual vs 33% target)"
- id=3: `layer_drift`, ticker=null, severity=78, confidence=90 — "L4 Convexity: underweight by 6.0pp (4.0% actual vs 10% target)"

**Severity verified deterministic:** `30 + int(5.2×8) = 71`, `30 + int(6.0×8) = 78`. LLM not called (calm day, all 33 positions below thresholds — max impact was GE at 0.26pp, max Z was XOM at 1.0).

**Unblocks:** 0012 (Critic Agent).

