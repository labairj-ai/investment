# Thesis Agent ADD Rec Lacks Valuation Gate

- **ID:** 0146
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** high
- **Depends:** none

## Problem

`run_thesis_monitor()` in `agents/thesis_agent.py` emits a BUY recommendation when `composite >= 80` and no violations/warnings exist (lines ~562-589). This fires purely on thesis health with no check on whether the stock is overvalued. A company can have excellent fundamentals and a strong thesis but also trade at 40× earnings with no margin of safety. Emitting BUY in that case is economically incorrect — thesis health and valuation are independent axes.

## Proposed approach

Before emitting the BUY rec, add a valuation guard:

1. Query `historical_valuation_metrics` for the latest PE or primary ratio value (same function used by `sell_trim_agent._score_V()`).
2. If a P/E percentile can be computed and the current ratio exceeds the thesis `valuation_framework.extreme_threshold` (or, if absent, a sensible default like 40× P/E), suppress the BUY and emit a HOLD_THESIS finding instead.
3. If no valuation data is available, emit BUY with a `"valuation_unverified": True` flag in `action_payload` and lower confidence.

The Sell/Trim V-score logic in `sell_trim_agent.py` already computes a valuation percentile via `_valuation_percentile()` and `_v_score_from_percentile()`; the thesis agent can call `agent_db.get_latest_valuation_metric(ticker)` and apply the same check.

## Touches

- `agents/thesis_agent.py` — ADD rule block (~lines 562-589): add valuation check before creating BUY rec
- `agent_db.py` — `get_latest_valuation_metric()` already exists (no change needed)

## Done when

- [ ] BUY rec is suppressed when current P/E (or primary ratio) exceeds extreme_threshold
- [ ] BUY rec carries `"valuation_unverified": True` when no valuation data is available
- [ ] Existing tests pass
