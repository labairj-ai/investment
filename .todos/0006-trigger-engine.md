# Build Deterministic Trigger Engine

- **ID:** 0006
- **Status:** backlog
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

## Done when

- [ ] `detect_triggers()` returns correct trigger types for a synthetic snapshot with known crossings
- [ ] No LLM calls in `triggers.py` (grep check)
- [ ] Trigger events include: agent_type, ticker, trigger_type, trigger_key, trigger_value
- [ ] Results are logged so it's auditable why each agent ran
- [ ] Thresholds are configurable via `strategy_config`, not hardcoded
- [ ] QA (backend): Call `detect_triggers()` with a synthetic snapshot that crosses at least one known threshold (e.g., position NAV impact > 0.35%, layer drift ≥ 5pp). Confirm the returned trigger list matches expected types and includes agent_type, ticker, trigger_type, trigger_key, trigger_value. Log actual output before checking this box — do NOT check based on reading the code.

