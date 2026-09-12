# Shadow Account Dashboard Panel

- **ID:** 0198
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0196

## Problem

Once the shadow execution loop works, the dashboard should surface the agentic account's activity so the system can be monitored and debugged before any live trading. This is also the first UI surface that demonstrates "the machine can propose, risk-check, and execute a trade" end-to-end.

## Proposed approach

**New API endpoints in `serve.py`:**

- `GET /api/shadow/account` — current cash, NAV, positions, account_id, trading_enabled
- `GET /api/shadow/intents?limit=20` — recent trade_intents with status, risk decision summary
- `GET /api/shadow/fills?limit=20` — recent fills with symbol, qty, price, linked recommendation_id
- `GET /api/shadow/risk/{intent_id}` — full risk_decision with per-rule check results

**Dashboard UI (new section, existing portfolio unchanged):**

Shadow Account panel showing:
```
AGENTIC SHADOW ACCOUNT           ● SHADOW MODE
────────────────────────────────────────────────
NAV: $10,847.20   Cash: $6,232.10   Positions: 3

RECENT INTENTS
────────────────────────────────────────────────
2026-09-12 10:35  BUY 10 ANET    FILLED @ $142.44
  Risk: ✓ 12/12 checks passed
  Account: $10,000 → $8,575.60

2026-09-11 14:20  BUY 7 GOOGL    REJECTED
  Risk: ✗ MAX_POSITION_WEIGHT (7.8% > 5% new position limit)

POSITIONS
────────────────────────────────────────────────
ANET    10 sh   avg $142.44   current $148.20   +4.1%
NVDA    5  sh   avg $127.80   current $131.50   +2.9%
```

The shadow panel is a read-only view. No action buttons, no trade submission from dashboard.

## Touches

- `serve.py` — 4 new GET endpoints
- `generate_dashboard.py` or dashboard HTML — new Shadow Account section
- `agent_db.py` — read helpers for shadow positions, fills, intents

## Done when

- [ ] `/api/shadow/account` returns cash, NAV, positions for AGENTIC_SHADOW_01
- [ ] `/api/shadow/intents` returns recent intents with status and one-line risk summary
- [ ] `/api/shadow/fills` returns fills linked to recommendation_ids
- [ ] `/api/shadow/risk/{intent_id}` returns full per-rule check results as JSON
- [ ] Dashboard panel shows account summary and recent activity
- [ ] Panel gracefully shows "no activity yet" when shadow account has no fills
- [ ] Existing dashboard sections are unchanged
