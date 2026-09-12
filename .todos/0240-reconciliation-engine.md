# ReconciliationEngine: Compare Broker vs Local State, Block on Mismatch

- **ID:** 0240
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0237, 0238

## Problem

There is no mechanism to detect discrepancies between what the broker reports and what the local SQLite database believes. For shadow mode this is fine because they're the same system. For paper/live mode, the broker is authoritative and local state is a replica — silent divergence would allow orders to be submitted against incorrect position or cash state.

A `ReconciliationEngine` must be the gate between "connected to broker" and "authorized to submit new orders."

## Proposed approach

**New file: `trade_engine/reconciliation.py`**

```python
from enum import Enum
from typing import NamedTuple, List

class DiscrepancyKind(str, Enum):
    MATCH = "MATCH"
    LOCAL_MISSING = "LOCAL_MISSING"
    BROKER_MISSING = "BROKER_MISSING"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    STATE_MISMATCH = "STATE_MISMATCH"
    CASH_MISMATCH = "CASH_MISMATCH"

class Discrepancy(NamedTuple):
    kind: DiscrepancyKind
    subject: str          # symbol, order_id, or "cash"
    local_value: object
    broker_value: object
    detail: str = ""

class ReconciliationResult(NamedTuple):
    ok: bool              # True only if all checks are MATCH or within tolerance
    discrepancies: List[Discrepancy]
    blocks_submission: bool  # True if any material discrepancy found

def reconcile(
    account_id: str,
    conn: sqlite3.Connection,
    broker: BrokerAdapter,
    *,
    cash_tolerance: float = 0.01,
    qty_tolerance: float = 0.0001,
) -> ReconciliationResult:
    ...
```

**Reconciliation checks (in order):**
1. **Cash**: compare `broker.get_broker_account().cash` vs `trading_accounts.current_cash`. If `|diff| > cash_tolerance` → `CASH_MISMATCH` (blocks submission).
2. **Positions**: for each position in `position_snapshots`, find matching `BrokerPosition` by symbol. Check qty within `qty_tolerance`. Classify `LOCAL_MISSING`, `BROKER_MISSING`, `QUANTITY_MISMATCH`.
3. **Open orders**: for each WORKING/PARTIALLY_FILLED local order, verify it exists in `broker.get_orders()` by `broker_order_id`. Classify `BROKER_MISSING` (broker cancelled it without our knowledge) or `STATE_MISMATCH`.
4. **Fills since last sync**: compare `broker.get_fills(since=last_sync_at)` against local `fills` table. Any fill in broker not in local DB → `LOCAL_MISSING` (needs to be imported).

**Integration with `run_execution_cycle()`:**
Add an optional `reconcile_first: bool = False` param to `run_execution_cycle()`. When `True`, run reconciliation before processing new intents. If `blocks_submission=True`, return `execution_state="HALTED"`, `halt_reason="RECONCILIATION_FAILED"`.

For shadow mode, reconciliation always returns `ok=True` since local state IS broker state.

**New test file: `tests/test_reconciliation.py`**
- Shadow-mode reconciliation: always MATCH
- Cash mismatch: broker says $9000, local says $10000 → CASH_MISMATCH, blocks_submission=True
- Position missing locally: broker has ANET 10 shares, local has none → BROKER_MISSING (not blocking but logged)
- Open order missing at broker: local has WORKING order, broker has no record → STATE_MISMATCH, blocks_submission=True

## Touches

- `trade_engine/reconciliation.py` — new file
- `trade_engine/execution_engine.py` — `run_execution_cycle()` optional reconciliation gate
- `tests/test_reconciliation.py` — new test file

## Done when

- [ ] `reconciliation.py` classifies MATCH, LOCAL_MISSING, BROKER_MISSING, QUANTITY_MISMATCH, STATE_MISMATCH, CASH_MISMATCH
- [ ] `ReconciliationResult.blocks_submission` is True for material mismatches (cash, missing broker order)
- [ ] Shadow reconciliation always returns `ok=True`
- [ ] `run_execution_cycle()` accepts `reconcile_first=False`; when True, halts if `blocks_submission`
- [ ] Tests cover all 6 discrepancy kinds
