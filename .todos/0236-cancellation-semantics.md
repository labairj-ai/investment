# Cancellation Semantics: IntentStatus.CANCELLED, cancel_reason, CANCEL_REQUESTED

- **ID:** 0236
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`_sync_intent_from_order()` (`execution_engine.py:56-61`) maps `OrderState.CANCELLED` → `IntentStatus.EXPIRED`. This conflates two very different events:

- **Expired**: DAY order reached 4:00 PM and was never filled.
- **Cancelled**: risk policy blocked a fill, user requested a cancel, position reconciliation failed, stale market data, broker rejected a replacement, etc.

When an external paper broker is wired in, cancellation becomes asynchronous:
- `CANCEL_REQUESTED` → `CANCELLED` (normal path)
- `CANCEL_REQUESTED` → `FILLED` (race: broker filled before cancel arrived — legal market behavior)

The current model has no way to represent pending cancellation or distinguish cancel reasons, which will cause silent misclassification of orders in the audit log.

## Proposed approach

**1. `trade_engine/models.py`:**
- Add `IntentStatus.CANCELLED = "CANCELLED"` (distinct from `EXPIRED`)
- Add `OrderState.CANCEL_REQUESTED = "CANCEL_REQUESTED"` with transition rules:
  - `CANCEL_REQUESTED` → allowed: `{CANCELLED, FILLED}` (fill-before-cancel race is legal)
  - `WORKING` → allowed: add `CANCEL_REQUESTED`
  - `PARTIALLY_FILLED` → allowed: add `CANCEL_REQUESTED`

**2. `agent_db.py` — schema migration:**
- Add columns to `orders`: `cancel_reason TEXT`, `cancel_requested_at TEXT`, `cancel_confirmed_at TEXT`
- Via `_new_cols` mechanism (already used for backward-compat schema migration)

**3. `trade_engine/execution_engine.py`:**
- Update `_sync_intent_from_order()`: map `OrderState.CANCELLED` → `IntentStatus.CANCELLED` (not EXPIRED)
- Update pre-fill rejection path (line 424): when risk rejects, set `cancel_reason="RISK_REVALIDATION_FAILED"`
- Update expiry path: map `OrderState.EXPIRED` → `IntentStatus.EXPIRED` (unchanged)

**4. `trade_engine/shadow_broker.py`:**
- Update `cancel_order()`: accept optional `reason: str = "USER_REQUESTED"`, write to `cancel_reason` and `cancel_requested_at`; immediately transitions WORKING/PARTIALLY_FILLED → `CANCEL_REQUESTED` → `CANCELLED` (shadow: synchronous cancel)
- Shadow adapter makes CANCEL_REQUESTED→CANCELLED atomic since there's no async broker

**5. Tests:**
- `_sync_intent_from_order` with CANCELLED order → IntentStatus.CANCELLED (not EXPIRED)
- `_sync_intent_from_order` with EXPIRED order → IntentStatus.EXPIRED (unchanged)
- Cancel with reason → `cancel_reason` written to DB
- Pre-fill rejection writes `cancel_reason="RISK_REVALIDATION_FAILED"`

## Touches

- `trade_engine/models.py` — `IntentStatus`, `OrderState`, `_STATE_TRANSITIONS`
- `trade_engine/execution_engine.py` — `_sync_intent_from_order()`, pre-fill rejection path
- `trade_engine/shadow_broker.py` — `cancel_order()`, `_apply_fill()` (CANCEL_REQUESTED→FILLED race path)
- `agent_db.py` — `_new_cols` additions for orders table
- `tests/test_trade_engine.py` — cancellation semantic tests

## Done when

- [ ] `IntentStatus.CANCELLED` exists and is distinct from `IntentStatus.EXPIRED`
- [ ] `OrderState.CANCEL_REQUESTED` exists; legal transitions include `→CANCELLED` and `→FILLED`
- [ ] `orders` table has `cancel_reason`, `cancel_requested_at`, `cancel_confirmed_at` columns
- [ ] `_sync_intent_from_order` maps `CANCELLED` → `IntentStatus.CANCELLED`, not `EXPIRED`
- [ ] Pre-fill risk rejection writes `cancel_reason="RISK_REVALIDATION_FAILED"`
- [ ] All existing tests pass
