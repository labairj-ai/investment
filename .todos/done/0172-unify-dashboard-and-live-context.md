# Unify Dashboard Context with Live Snapshot

- **ID:** 0172
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** low
- **Depends:** none

## Problem

`_build_mgmt_context_from_db()` (the dashboard path) reads stale `portfolio_day` / `holding_day` rows to build a `ManagementPolicyContext`, while `agents/covered_call_agent.py` `_analyze_roll()` fetches a live market snapshot. The two paths can reach different decisions for the same position at the same moment — most visibly when market price has moved significantly since last DB write. Users see one recommendation in the dashboard and a different one from the agent.

## Proposed approach

Refactor `_build_mgmt_context_from_db()` to optionally accept a live price override:

```python
def _build_mgmt_context_from_db(ticker, expiry, strike, ..., live_price: float | None = None) -> ManagementPolicyContext:
```

When `live_price` is provided, use it for `current_price` instead of the stale DB row. The dashboard endpoint can pass `None` (keep current behavior) or be wired to fetch a cached quote. Long-term the two paths should share a single context-builder, but this is a low-risk first step.

Alternatively, expose a `/api/cc/evaluate` endpoint that re-runs the full live evaluation on demand and the dashboard calls that instead of reading stale rows directly.

## Touches

- `covered_call_rec.py` — `_build_mgmt_context_from_db()` signature
- `serve.py` — dashboard endpoint that calls `_build_mgmt_context_from_db()`
- Possibly `agents/covered_call_agent.py` if context builder is unified

## Done when

- [ ] Dashboard and agent paths use the same price source (or caller can inject live price)
- [ ] No functional regression in dashboard CC management cards
- [ ] Unit test or manual verification that dashboard result matches agent result for same inputs
