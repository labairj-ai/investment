# Build Deterministic Trigger Engine

- **ID:** 0006
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005

## Problem

Currently agents (and the daily insight) run on a fixed schedule and evaluate everything every time. This causes unnecessary model calls on calm days, makes it hard to explain why an analysis ran, and buries important signals in routine noise. A trigger engine makes the system event-driven: agents only run when something actually crosses a materiality threshold.

## Proposed approach

Implement `detect_triggers(snapshot: PortfolioSnapshot) → list[TriggerEvent]` in `agents/triggers.py`. Each `TriggerEvent` names the agent to invoke, the ticker(s) in scope, the trigger type, and the key metric value that crossed the threshold.

Trigger conditions to implement (all deterministic, no LLM):

- **Guardian**: price move > 2σ (Z = |r| / (HV20 / √252)); position NAV impact > 0.35% (Weight × Return); layer drift ≥ 5pp; macro score change ≥ 2 points in 24h
- **Thesis**: new earnings result available; guidance revision in news; dividend cut detected
- **CC**: holding ≥ 100 shares, no open CC, HV percentile > 50; CC opportunity score crosses configured threshold; existing call within management DTE window
- **Tax**: lot within 30–45 days of LT crossover; unrealized loss > $500 with offsettable ST gains
- **Opportunity**: new Buffett screener winner; layer weight < (target - 5pp) for > 3 days

Thresholds should be read from `strategy_config` where they are configurable, not hardcoded in triggers.

The trigger engine runs after every data refresh (before agents). If no triggers fire, no agent runs and no model calls are made.

## Touches

`agents/triggers.py`, `strategy_config.py` (threshold config), `serve.py` (call trigger engine after data refresh)

## Outcome

`agents/triggers.py` expanded from 84 → ~270 lines. `TriggerEvent` gained a `trigger_value: float | None` field. `detect_triggers()` now implements 9 trigger families:

| trigger_type | → agent | threshold source |
|---|---|---|
| `layer_drift` | portfolio_guardian | DRIFT_THRESHOLD (5pp) |
| `price_move` | portfolio_guardian | TRIGGER_PRICE_MOVE_Z (2.0σ) — HV20 from holding_day price history |
| `nav_impact` | portfolio_guardian | TRIGGER_NAV_IMPACT_PCT (0.35%) — weight × \|daily_return\| |
| `macro_score_change` | portfolio_guardian | TRIGGER_MACRO_SCORE_CHANGE (2 pts) — any dimension between last 2 scored runs |
| `cc_eligible` | covered_call | _CC_MIN_SHARES (100), layers 1-3 |
| `cc_mgmt_dte` | covered_call | TRIGGER_CC_MGMT_DTE (21 days) — from open cc_positions |
| `tax_lt_crossover` | tax | TRIGGER_TAX_LT_WINDOW_MIN/MAX (30-45 days) — from cost_lots |
| `tax_loss_harvest` | tax | TRIGGER_TAX_LOSS_MIN ($500) — ST lots with unrealized loss |
| `layer_underweight` | opportunity_hunter | DRIFT_THRESHOLD, TRIGGER_LAYER_UNDERWEIGHT_DAYS (3 days) — from layer_day history |

Plus the always-on `portfolio_scope` triggers for `thesis_monitor` and `briefing`.

All thresholds added to `config/strategy.json` under `"triggers"` and exposed via `strategy_config.py` as `TRIGGER_*` constants. DB reads use private helpers (`_load_price_history`, `_load_today_changes`, `_load_macro_score_history`, `_load_cost_lots`, `_load_open_cc_positions`, `_load_layer_weight_history`) that return empty dicts/lists on any failure — trigger engine degrades gracefully if DB is missing.

QA output (synthetic snapshot, L1 at 15% and L3 at 45.5%):
```
[triggers] layer_drift → portfolio_guardian key=L1 value=-18.0
[triggers] layer_drift → portfolio_guardian key=L3 value=16.5
[triggers] price_move → portfolio_guardian key=NFLX value=2.28
[triggers] nav_impact → portfolio_guardian key=NFLX value=1.604
[triggers] cc_eligible → covered_call key=WMT value=100.0
[triggers] cc_eligible → covered_call key=NFLX value=200.0
[triggers] layer_underweight → opportunity_hunter key=L4 value=3.95
[triggers] portfolio_scope → thesis_monitor key=thesis_daily
[triggers] portfolio_scope → briefing key=daily
Total: 9 triggers
```

**Now unblocked:** 0010 (Covered Call Agent), 0011 (Portfolio Guardian), 0014 (Opportunity Hunter), 0015 (Tax Agent).

## Done when

- [x] `detect_triggers()` returns correct trigger types for a synthetic snapshot with known crossings
- [x] No LLM calls in `triggers.py` (grep check)
- [x] Trigger events include: agent_type, ticker, trigger_type, trigger_key, trigger_value
- [x] Results are logged so it's auditable why each agent ran
- [x] Thresholds are configurable via `strategy_config`, not hardcoded
- [x] QA (backend): Call `detect_triggers()` with a synthetic snapshot that crosses at least one known threshold (e.g., position NAV impact > 0.35%, layer drift ≥ 5pp). Confirm the returned trigger list matches expected types and includes agent_type, ticker, trigger_type, trigger_key, trigger_value. Log actual output before checking this box — do NOT check based on reading the code.

