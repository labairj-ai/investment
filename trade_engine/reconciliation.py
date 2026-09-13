"""ReconciliationEngine: compare broker state vs local SQLite and classify discrepancies (0240).

For shadow mode, local state IS broker state — reconciliation is always MATCH.
For paper/live, the broker is authoritative; any unexplained material mismatch
blocks new order submission until resolved.
"""
from __future__ import annotations

import sqlite3
from enum import Enum
from typing import TYPE_CHECKING, List, NamedTuple, Optional

if TYPE_CHECKING:
    from .broker_adapter import BrokerAdapter


class DiscrepancyKind(str, Enum):
    MATCH = "MATCH"
    LOCAL_MISSING = "LOCAL_MISSING"       # broker has it; local DB doesn't
    BROKER_MISSING = "BROKER_MISSING"     # local DB has it; broker doesn't
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    STATE_MISMATCH = "STATE_MISMATCH"
    CASH_MISMATCH = "CASH_MISMATCH"


# Discrepancy kinds that block new order submission
_BLOCKING_KINDS = {
    DiscrepancyKind.CASH_MISMATCH,
    DiscrepancyKind.BROKER_MISSING,     # open order missing at broker
    DiscrepancyKind.STATE_MISMATCH,     # order in wrong state
}


class Discrepancy(NamedTuple):
    kind: DiscrepancyKind
    subject: str          # symbol, order_id, or "cash"
    local_value: object
    broker_value: object
    detail: str = ""


class ReconciliationResult(NamedTuple):
    ok: bool
    discrepancies: List[Discrepancy]
    blocks_submission: bool


def reconcile(
    account_id: str,
    conn: sqlite3.Connection,
    broker: "BrokerAdapter",
    *,
    cash_tolerance: float = 0.01,
    qty_tolerance: float = 0.0001,
) -> ReconciliationResult:
    """Compare broker-reported state against local SQLite and classify discrepancies.

    Checks (in order):
    1. Cash — material difference blocks submission
    2. Positions — qty mismatch logged; does not block (positions drift from fills we may not have imported yet)
    3. Open orders — order present locally but missing at broker blocks submission
    4. (Fills import is handled by initialize_trading_session; not checked here)

    For shadow mode, broker IS local state, so all checks return MATCH trivially.
    """
    discrepancies: List[Discrepancy] = []

    # ── 1. Cash ───────────────────────────────────────────────────────────────
    try:
        broker_acct = broker.get_broker_account(account_id)
        local_row = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if local_row:
            local_cash = float(local_row["current_cash"] or 0)
            diff = abs(local_cash - broker_acct.cash)
            if diff > cash_tolerance:
                discrepancies.append(Discrepancy(
                    kind=DiscrepancyKind.CASH_MISMATCH,
                    subject="cash",
                    local_value=round(local_cash, 4),
                    broker_value=round(broker_acct.cash, 4),
                    detail=f"diff=${diff:.4f}",
                ))
    except Exception as exc:
        discrepancies.append(Discrepancy(
            kind=DiscrepancyKind.BROKER_MISSING,
            subject="account",
            local_value=account_id,
            broker_value=None,
            detail=str(exc),
        ))

    # ── 2. Positions ──────────────────────────────────────────────────────────
    try:
        broker_positions = {p.symbol: p for p in broker.get_positions(account_id)}
        local_pos_rows = conn.execute(
            "SELECT symbol, qty FROM position_snapshots WHERE account_id=?", (account_id,)
        ).fetchall()
        local_positions = {r["symbol"]: float(r["qty"] or 0) for r in local_pos_rows}

        for symbol, local_qty in local_positions.items():
            if symbol not in broker_positions:
                discrepancies.append(Discrepancy(
                    kind=DiscrepancyKind.BROKER_MISSING,
                    subject=symbol,
                    local_value=local_qty,
                    broker_value=0.0,
                    detail="position in local DB not at broker",
                ))
            elif abs(local_qty - broker_positions[symbol].qty) > qty_tolerance:
                discrepancies.append(Discrepancy(
                    kind=DiscrepancyKind.QUANTITY_MISMATCH,
                    subject=symbol,
                    local_value=local_qty,
                    broker_value=broker_positions[symbol].qty,
                    detail=f"diff={abs(local_qty - broker_positions[symbol].qty):.6f}",
                ))

        for symbol, bpos in broker_positions.items():
            if symbol not in local_positions:
                discrepancies.append(Discrepancy(
                    kind=DiscrepancyKind.LOCAL_MISSING,
                    subject=symbol,
                    local_value=0.0,
                    broker_value=bpos.qty,
                    detail="position at broker not in local DB",
                ))
    except Exception:
        pass  # position comparison is best-effort; cash and order checks are primary gates

    # ── 3. Open orders ────────────────────────────────────────────────────────
    try:
        broker_orders = {o.local_order_id or o.broker_order_id: o
                         for o in broker.get_open_orders(account_id)}
        local_open_rows = conn.execute(
            "SELECT order_id, state FROM orders WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')",
            (account_id,),
        ).fetchall()

        for row in local_open_rows:
            oid = row["order_id"]
            if oid not in broker_orders:
                discrepancies.append(Discrepancy(
                    kind=DiscrepancyKind.BROKER_MISSING,
                    subject=oid,
                    local_value=row["state"],
                    broker_value=None,
                    detail="WORKING order in local DB is missing at broker",
                ))
            else:
                broker_state = broker_orders[oid].state
                local_state = row["state"]
                if broker_state != local_state:
                    discrepancies.append(Discrepancy(
                        kind=DiscrepancyKind.STATE_MISMATCH,
                        subject=oid,
                        local_value=local_state,
                        broker_value=broker_state,
                    ))
    except Exception:
        pass

    blocks = any(d.kind in _BLOCKING_KINDS for d in discrepancies)
    ok = len(discrepancies) == 0

    return ReconciliationResult(
        ok=ok,
        discrepancies=discrepancies,
        blocks_submission=blocks,
    )
