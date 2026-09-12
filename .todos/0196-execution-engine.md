# Execution Engine: Orchestrate Intent → Risk → Shadow → Fill → Outcome

- **ID:** 0196
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0193, 0194, 0195

## Problem

Each component (risk engine, shadow broker, intent builder) has its own responsibility. The execution engine orchestrates them into a single durable loop and wires fills back into the existing `executed_actions` + outcome evaluation machinery so that shadow trades benefit from the same Decision Quality infrastructure already built.

## Proposed approach

**`trade_engine/execution_engine.py`**

```python
def process_intent(intent_id: str) -> ExecutionResult: ...
def run_pending_intents(account_id: str) -> list[ExecutionResult]: ...
```

`process_intent()` pipeline:
```
load TradeIntent from DB
  ↓
load TradingPolicy for account
  ↓
load TradingAccount from DB
  ↓
Risk Engine evaluate() → RiskDecision
  ├─ REJECTED → update intent status=REJECTED, write risk_decision, return
  ↓ APPROVED
update intent status=APPROVED
  ↓
ShadowBroker.submit_order() → Order (SUBMITTED state)
  ↓
ShadowBroker.attempt_fill(order, current_quote)
  ├─ no fill → order stays WORKING; schedule re-attempt later
  ↓ fill
update intent status=FILLED
  ↓
write Fill to fills table (atomic with order+position+cash update)
  ↓
write to executed_actions (existing schema) — links fill back to recommendation
  ↓
trigger outcome evaluator for this recommendation
```

**Key invariants:**
- If the process crashes after writing the order but before the fill, restart finds the order in SUBMITTED/WORKING state and re-attempts fill without re-running risk or re-submitting order.
- If the process crashes after the fill but before writing to executed_actions, the fill is idempotent (fill_id unique index) and executed_actions uses fill_id for dedup.
- `run_pending_intents()` is the entry point for the serve.py scheduler — runs on a configurable interval (e.g. every 60s during market hours).

**`executed_actions` bridge:**
Shadow fills are written to the existing `executed_actions` table using the same schema, with `fill_source='shadow'` in the notes/metadata field. This allows the existing outcome evaluator (`evaluate_matured_recommendations()` in `outcome_evaluator.py`) to process shadow recommendations exactly as it processes live ones.

**`ExecutionResult`:**
```python
@dataclass
class ExecutionResult:
    intent_id: str
    decision: str          # 'APPROVED' | 'REJECTED'
    order_id: str | None
    fill: Fill | None
    risk_decision: RiskDecision
    elapsed_ms: int
```

## Touches

- `trade_engine/execution_engine.py`
- `serve.py` — add `/api/trade-engine/run` endpoint + optional scheduler hook
- `agent_db.py` — executed_actions write for shadow fills

## Done when

- [ ] `process_intent()` runs the full pipeline for a BUY intent
- [ ] REJECTED intent is persisted to risk_decisions; no order created
- [ ] APPROVED intent creates order, attempts fill, writes fill + position + cash atomically
- [ ] Shadow fill written to executed_actions with correct recommendation_id linkage
- [ ] Outcome evaluator can process the shadow recommendation at maturity
- [ ] Crash after order submit but before fill: restart finds WORKING order, no duplicate
- [ ] Crash after fill: re-run is idempotent (no double-counting via fill_id dedup)
- [ ] `run_pending_intents()` processes all PENDING intents for the account
- [ ] `/api/trade-engine/run` triggers `run_pending_intents` for AGENTIC_SHADOW_01
- [ ] Integration test: BUY recommendation → full pipeline → verified fill in executed_actions
