# Dashboard Weight: Use Canonical Live Snapshot

- **ID:** 0184
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`_build_mgmt_context_from_db()` calculates `current_weight_pct` from `holding_day` / `portfolio_day` rows — the most recent end-of-day records. The code itself describes this as the "stale holding_day fallback."

The covered-call agent, however, builds `ManagementPolicyContext` from the live canonical snapshot (`AgentContext.snapshot`), which uses intraday prices. This divergence means an intraday price move can produce different `only_if_overweight` decisions between:
- the dashboard (`_build_mgmt_context_from_db()`) — uses yesterday's close
- the agent — uses live quote

The divergence is a P2 integration issue (not a P1 blocker now that 0174 is done), because the agent's decision is authoritative. The dashboard path is advisory/display-only. But it's confusing and can show stale gate reasoning to the user.

## Proposed approach

In `_build_mgmt_context_from_db()`, attempt to read current weight from `portfolio_positions` (if the table exists) before falling back to `holding_day` / `portfolio_day`:

1. Try `SELECT shares, current_price FROM portfolio_positions WHERE ticker=?` + compute weight as `shares × current_price / sum(shares × current_price)`.
2. If `portfolio_positions` is absent or has no row for the ticker, fall back to the existing `holding_day` / `portfolio_day` query.
3. If both are unavailable, leave `current_weight_pct = None` (gate skips, same as today).

`portfolio_positions` is updated at dashboard generation time with live prices, so it is more current than `holding_day` (which is written once per day by the portfolio recorder).

If `portfolio_positions` doesn't exist in the schema, consider adding a generation-time write of computed weights to a lightweight `live_weights` view or ephemeral table. Coordinate with the generate_dashboard step.

**Important:** do not change the agent path — it should continue using its existing live snapshot. This change is scoped to the dashboard's `_build_mgmt_context_from_db()` function only.

## Touches

- `covered_call_rec.py` — `_build_mgmt_context_from_db()` portfolio weight block (~line 1121–1139)
- May touch `generate_dashboard.py` or `serve.py` if a `live_weights` table needs to be written
- `tests/test_cc_management.py` — optionally test that `portfolio_positions` weight takes priority over `holding_day`

## Done when

- [ ] `_build_mgmt_context_from_db()` tries `portfolio_positions` weight before `holding_day` fallback
- [ ] Falls back gracefully when `portfolio_positions` is absent or has no row
- [ ] Dashboard `only_if_overweight` decision matches agent more closely for intraday price moves
- [ ] All existing tests pass
