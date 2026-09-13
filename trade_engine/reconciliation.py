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
    LOCAL_MISSING = "LOCAL_MISSING"                   # broker has it; local DB doesn't
    BROKER_MISSING = "BROKER_MISSING"                 # local DB has it; broker doesn't
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    STATE_MISMATCH = "STATE_MISMATCH"
    CASH_MISMATCH = "CASH_MISMATCH"
    RECONCILIATION_UNAVAILABLE = "RECONCILIATION_UNAVAILABLE"  # retrieval failure (0246)


# Discrepancy kinds that block new order submission
_BLOCKING_KINDS = {
    DiscrepancyKind.CASH_MISMATCH,
    DiscrepancyKind.LOCAL_MISSING,                # broker has it; local DB doesn't — blocks (0257)
    DiscrepancyKind.BROKER_MISSING,               # open order/position missing at broker
    DiscrepancyKind.STATE_MISMATCH,               # order in wrong state
    DiscrepancyKind.QUANTITY_MISMATCH,            # position qty mismatch blocks after fills (0246)
    DiscrepancyKind.RECONCILIATION_UNAVAILABLE,   # any retrieval failure blocks submission (0246)
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
    except Exception as exc:
        # Retrieval failure blocks submission — fail closed (0246)
        discrepancies.append(Discrepancy(
            kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
            subject="positions",
            local_value=None,
            broker_value=None,
            detail=str(exc),
        ))

    # ── 3. Open orders ────────────────────────────────────────────────────────
    try:
        # Index by local_order_id, then client_order_id, then broker_order_id (0247)
        broker_order_list = broker.get_open_orders(account_id)
        broker_orders = {}
        for o in broker_order_list:
            key = o.local_order_id or o.client_order_id or o.broker_order_id
            broker_orders[key] = o
        local_open_rows = conn.execute(
            "SELECT order_id, state, client_order_id FROM orders WHERE account_id=? AND state IN ('PENDING_SUBMIT','WORKING','PARTIALLY_FILLED')",
            (account_id,),
        ).fetchall()

        # ── 3a. Local → broker: local open orders that are missing at broker ──
        for row in local_open_rows:
            oid = row["order_id"]
            # PENDING_SUBMIT rows may not yet appear in broker_orders by order_id;
            # check by client_order_id below in 3b (UPDATE path)
            if row["state"] == "PENDING_SUBMIT":
                continue
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

        # ── 3b. Broker → local: broker open orders with no local record (0257) ─
        local_order_ids = {row["order_id"] for row in local_open_rows}
        for bo in broker_order_list:
            bo_key = bo.local_order_id or bo.broker_order_id
            if bo_key in local_order_ids:
                continue  # already matched in local→broker pass

            # Attempt auto-import when client_order_id traces back to a known intent
            imported = False
            if bo.client_order_id:
                from datetime import datetime, timezone as _tz
                now_str = datetime.now(_tz.utc).isoformat()

                # PENDING_SUBMIT recovery (0260): if a local PENDING_SUBMIT row matches
                # this broker order by client_order_id, UPDATE it to WORKING rather than
                # attempting a second INSERT (which would be silently ignored).
                pending_row = conn.execute(
                    "SELECT order_id FROM orders WHERE client_order_id=? AND state='PENDING_SUBMIT'",
                    (bo.client_order_id,),
                ).fetchone()
                if pending_row:
                    conn.execute(
                        """UPDATE orders
                           SET state='WORKING', broker_order_id=?, submitted_at=?, updated_at=?
                           WHERE order_id=?""",
                        (bo.broker_order_id or bo_key, now_str, now_str, pending_row["order_id"]),
                    )
                    conn.commit()
                    imported = True

                if not imported:
                    parts = bo.client_order_id.split(":", 1)
                    if len(parts) == 2:
                        intent_id = parts[1]
                        intent_row = conn.execute(
                            "SELECT intent_id FROM trade_intents WHERE intent_id=? AND account_id=?",
                            (intent_id, account_id),
                        ).fetchone()
                        if intent_row:
                            # Import: create local order row from broker-reported state
                            conn.execute(
                                """INSERT OR IGNORE INTO orders
                                   (order_id, intent_id, account_id, symbol, side, quantity,
                                    order_type, state, fill_qty, fill_cash,
                                    client_order_id, submitted_at, updated_at)
                                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    bo_key, intent_id, account_id,
                                    bo.symbol, bo.side, bo.quantity,
                                    "LIMIT", bo.state, bo.fill_qty, 0.0,
                                    bo.client_order_id, now_str, now_str,
                                ),
                            )
                            conn.commit()
                            imported = True

            if not imported:
                discrepancies.append(Discrepancy(
                    kind=DiscrepancyKind.LOCAL_MISSING,
                    subject=bo_key,
                    local_value=None,
                    broker_value=bo.state,
                    detail="broker has open order with no matching local DB record",
                ))
    except Exception as exc:
        # Retrieval failure blocks submission — fail closed (0246)
        discrepancies.append(Discrepancy(
            kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
            subject="open_orders",
            local_value=None,
            broker_value=None,
            detail=str(exc),
        ))

    blocks = any(d.kind in _BLOCKING_KINDS for d in discrepancies)
    ok = len(discrepancies) == 0

    return ReconciliationResult(
        ok=ok,
        discrepancies=discrepancies,
        blocks_submission=blocks,
    )
