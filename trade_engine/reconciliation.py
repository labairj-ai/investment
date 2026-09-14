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
        from .execution_engine import resolve_local_order_id  # local import avoids circular dep
        broker_order_list = broker.get_open_orders(account_id)
        local_open_rows = conn.execute(
            "SELECT order_id, state, client_order_id, broker_order_id FROM orders WHERE account_id=? AND state IN ('PENDING_SUBMIT','WORKING','PARTIALLY_FILLED')",
            (account_id,),
        ).fetchall()

        # Build broker orders indexed by resolved LOCAL order_id (0269).
        # Prevents false BROKER_MISSING when broker uses a different ID namespace.
        broker_orders_by_local: dict = {}
        for bo in broker_order_list:
            bo_cid = getattr(bo, "client_order_id", None)
            local_id = resolve_local_order_id(bo.local_order_id, bo.broker_order_id, bo_cid, conn)
            if local_id:
                broker_orders_by_local[local_id] = bo
            else:
                # New broker order with no local row yet; store by broker_order_id as fallback
                broker_orders_by_local.setdefault(bo.broker_order_id, bo)

        # ── 3a. Local → broker: check WORKING/PARTIALLY_FILLED orders (0269) ──
        for row in local_open_rows:
            oid = row["order_id"]
            if row["state"] == "PENDING_SUBMIT":
                continue  # handled explicitly by 3c below
            if oid not in broker_orders_by_local:
                broker_oid = row["broker_order_id"]
                if broker_oid:
                    # Order was submitted; look it up directly before declaring BROKER_MISSING (0302).
                    # A DAY order that expired while down should resolve cleanly, not force manual intervention.
                    try:
                        _looked_up = broker.get_order(broker_oid)
                    except Exception as _go_exc:
                        discrepancies.append(Discrepancy(
                            kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                            subject=oid,
                            local_value=row["state"],
                            broker_value=None,
                            detail=f"get_order({broker_oid!r}) raised {type(_go_exc).__name__}: {_go_exc}",
                        ))
                    else:
                        if _looked_up is None:
                            # Broker returns 404 — uncertain; never infer terminal state from absence (0302).
                            discrepancies.append(Discrepancy(
                                kind=DiscrepancyKind.BROKER_MISSING,
                                subject=oid,
                                local_value=row["state"],
                                broker_value=None,
                                detail=f"get_order({broker_oid!r}) returned None — broker has no record",
                            ))
                        elif _looked_up.state in ("WORKING", "PARTIALLY_FILLED"):
                            # Still open at broker but absent from open-orders list — genuine discrepancy
                            discrepancies.append(Discrepancy(
                                kind=DiscrepancyKind.BROKER_MISSING,
                                subject=oid,
                                local_value=row["state"],
                                broker_value=_looked_up.state,
                                detail="absent from broker open-orders list but get_order() shows still open",
                            ))
                        elif _looked_up.state == "FILLED":
                            from datetime import datetime, timezone as _tz
                            from .execution_engine import apply_broker_fill  # local import avoids circular dep
                            _now_r = datetime.now(_tz.utc).isoformat()
                            conn.execute(
                                "UPDATE orders SET state='WORKING', broker_order_id=?, updated_at=? WHERE order_id=?",
                                (broker_oid, _now_r, oid),
                            )
                            conn.commit()
                            try:
                                _reco_fills = broker.get_fills_for_order(broker_oid)
                            except Exception as _reco_exc:
                                discrepancies.append(Discrepancy(
                                    kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                                    subject=oid,
                                    local_value="FILLED",
                                    broker_value="FILLED",
                                    detail=f"get_fills_for_order() raised {type(_reco_exc).__name__}",
                                ))
                            else:
                                if not _reco_fills:
                                    discrepancies.append(Discrepancy(
                                        kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                                        subject=oid,
                                        local_value="FILLED",
                                        broker_value="FILLED",
                                        detail="broker reports FILLED but fills endpoint returned empty",
                                    ))
                                for _rf in _reco_fills:
                                    apply_broker_fill(_rf, account_id, conn)
                        elif _looked_up.state in ("CANCELLED", "REJECTED", "EXPIRED"):
                            from datetime import datetime, timezone as _tz
                            _now_r = datetime.now(_tz.utc).isoformat()
                            conn.execute(
                                "UPDATE orders SET state=?, broker_order_id=?, updated_at=? WHERE order_id=?",
                                (_looked_up.state, broker_oid, _now_r, oid),
                            )
                            _intent_status = {"CANCELLED": "CANCELLED", "REJECTED": "REJECTED", "EXPIRED": "EXPIRED"}[_looked_up.state]
                            conn.execute(
                                """UPDATE trade_intents SET status=?
                                   WHERE intent_id = (SELECT intent_id FROM orders WHERE order_id=?)""",
                                (_intent_status, oid),
                            )
                            conn.commit()
                        else:
                            discrepancies.append(Discrepancy(
                                kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                                subject=oid,
                                local_value=row["state"],
                                broker_value=_looked_up.state,
                                detail=f"unknown broker state {_looked_up.state!r} returned by get_order()",
                            ))
                else:
                    discrepancies.append(Discrepancy(
                        kind=DiscrepancyKind.BROKER_MISSING,
                        subject=oid,
                        local_value=row["state"],
                        broker_value=None,
                        detail="WORKING order in local DB is missing at broker (no broker_order_id to look up)",
                    ))
            else:
                broker_state = broker_orders_by_local[oid].state
                local_state = row["state"]
                if broker_state != local_state:
                    discrepancies.append(Discrepancy(
                        kind=DiscrepancyKind.STATE_MISMATCH,
                        subject=oid,
                        local_value=local_state,
                        broker_value=broker_state,
                    ))

        # ── 3b. Broker → local: import broker orders with no local record (0257) ─
        local_order_ids = {row["order_id"] for row in local_open_rows}
        for bo in broker_order_list:
            bo_cid = getattr(bo, "client_order_id", None)
            bo_local_id = resolve_local_order_id(bo.local_order_id, bo.broker_order_id, bo_cid, conn)
            if bo_local_id and bo_local_id in local_order_ids:
                continue  # already matched via resolver

            # Attempt auto-import when client_order_id traces back to a known intent
            imported = False
            if bo_cid:
                from datetime import datetime, timezone as _tz
                now_str = datetime.now(_tz.utc).isoformat()

                # PENDING_SUBMIT recovery (0260): UPDATE to WORKING
                pending_row = conn.execute(
                    "SELECT order_id FROM orders WHERE client_order_id=? AND state='PENDING_SUBMIT'",
                    (bo_cid,),
                ).fetchone()
                if pending_row:
                    conn.execute(
                        """UPDATE orders
                           SET state='WORKING', broker_order_id=?, submitted_at=?, updated_at=?
                           WHERE order_id=?""",
                        (bo.broker_order_id or bo.local_order_id or bo.broker_order_id, now_str, now_str, pending_row["order_id"]),
                    )
                    conn.commit()
                    imported = True

                if not imported:
                    parts = bo_cid.split(":", 1)
                    if len(parts) == 2:
                        intent_id = parts[1]
                        intent_row = conn.execute(
                            "SELECT intent_id FROM trade_intents WHERE intent_id=? AND account_id=?",
                            (intent_id, account_id),
                        ).fetchone()
                        if intent_row:
                            bo_key = bo.local_order_id or bo.broker_order_id
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
                                    bo_cid, now_str, now_str,
                                ),
                            )
                            conn.commit()
                            imported = True

            if not imported:
                discrepancies.append(Discrepancy(
                    kind=DiscrepancyKind.LOCAL_MISSING,
                    subject=bo.local_order_id or bo.broker_order_id,
                    local_value=None,
                    broker_value=bo.state,
                    detail="broker has open order with no matching local DB record",
                ))

        # ── 3c. PENDING_SUBMIT resolution (0270) ─────────────────────────────
        # Any remaining PENDING_SUBMIT rows must be explicitly resolved before TRADING_READY.
        # Without this, a submit_lost crash leaves a ghost PENDING_SUBMIT that silently clears.
        pending_submit_rows = conn.execute(
            "SELECT order_id, client_order_id FROM orders WHERE account_id=? AND state='PENDING_SUBMIT'",
            (account_id,),
        ).fetchall()
        for prow in pending_submit_rows:
            pcid = prow["client_order_id"]
            if not pcid:
                discrepancies.append(Discrepancy(
                    kind=DiscrepancyKind.BROKER_MISSING,
                    subject=prow["order_id"],
                    local_value="PENDING_SUBMIT",
                    broker_value=None,
                    detail="PENDING_SUBMIT order has no client_order_id; cannot verify with broker",
                ))
                continue
            try:
                bo = broker.find_order_by_client_order_id(pcid)
            except Exception as exc:
                discrepancies.append(Discrepancy(
                    kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                    subject=prow["order_id"],
                    local_value="PENDING_SUBMIT",
                    broker_value=None,
                    detail=f"find_order_by_client_order_id failed: {exc}",
                ))
                continue
            from datetime import datetime, timezone as _tz
            from .execution_engine import apply_broker_fill  # local import avoids circular dep
            now_str = datetime.now(_tz.utc).isoformat()
            if bo is not None:
                # Broker returned an order — apply state-specific recovery reducer (0274).
                _bstate = bo.state if bo.state else "WORKING"
                if _bstate == "WORKING":
                    conn.execute(
                        """UPDATE orders SET state='WORKING', broker_order_id=?, submitted_at=?, updated_at=?
                           WHERE order_id=?""",
                        (bo.broker_order_id, now_str, now_str, prow["order_id"]),
                    )
                    conn.commit()
                elif _bstate == "PARTIALLY_FILLED":
                    # Broker has partial fills; open order, fetch fills, let ledger own state (0279, 0282).
                    conn.execute(
                        """UPDATE orders SET state='WORKING', broker_order_id=?, submitted_at=?, updated_at=?
                           WHERE order_id=?""",
                        (bo.broker_order_id, now_str, now_str, prow["order_id"]),
                    )
                    conn.commit()
                    try:
                        _pf_reco_fills = broker.get_fills_for_order(bo.broker_order_id)
                    except Exception as _pf_reco_exc:
                        discrepancies.append(Discrepancy(
                            kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                            subject=prow["order_id"],
                            local_value="PARTIALLY_FILLED",
                            broker_value="PARTIALLY_FILLED",
                            detail=f"get_fills_for_order() raised {type(_pf_reco_exc).__name__}",
                        ))
                        _pf_reco_fills = []
                    else:
                        if not _pf_reco_fills:
                            discrepancies.append(Discrepancy(
                                kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                                subject=prow["order_id"],
                                local_value="PARTIALLY_FILLED",
                                broker_value="PARTIALLY_FILLED",
                                detail="broker reports PARTIALLY_FILLED but fills endpoint returned empty",
                            ))
                    for _rf in _pf_reco_fills:
                        apply_broker_fill(_rf, account_id, conn)
                elif _bstate == "PENDING":
                    # Broker queued but not yet active — keep as PENDING_SUBMIT
                    conn.execute(
                        "UPDATE orders SET broker_order_id=?, updated_at=? WHERE order_id=?",
                        (bo.broker_order_id, now_str, prow["order_id"]),
                    )
                    conn.commit()
                elif _bstate == "FILLED":
                    # Broker filled before restart — ingest authoritative fills then mark FILLED (0282).
                    conn.execute(
                        """UPDATE orders SET state='WORKING', broker_order_id=?, submitted_at=?, updated_at=?
                           WHERE order_id=?""",
                        (bo.broker_order_id, now_str, now_str, prow["order_id"]),
                    )
                    conn.commit()
                    try:
                        _reco_fills = broker.get_fills_for_order(bo.broker_order_id)
                    except Exception as _reco_exc:
                        discrepancies.append(Discrepancy(
                            kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                            subject=prow["order_id"],
                            local_value="FILLED",
                            broker_value="FILLED",
                            detail=f"get_fills_for_order() raised {type(_reco_exc).__name__}",
                        ))
                        _reco_fills = []
                    else:
                        if not _reco_fills:
                            discrepancies.append(Discrepancy(
                                kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                                subject=prow["order_id"],
                                local_value="FILLED",
                                broker_value="FILLED",
                                detail="broker reports FILLED but fills endpoint returned empty",
                            ))
                    for _rf in _reco_fills:
                        apply_broker_fill(_rf, account_id, conn)
                elif _bstate in ("CANCELLED", "REJECTED", "EXPIRED"):
                    _local_terminal = _bstate
                    conn.execute(
                        "UPDATE orders SET state=?, broker_order_id=?, updated_at=? WHERE order_id=?",
                        (_local_terminal, bo.broker_order_id, now_str, prow["order_id"]),
                    )
                    _intent_status = {
                        "CANCELLED": "CANCELLED",
                        "REJECTED": "REJECTED",
                        "EXPIRED": "EXPIRED",
                    }[_local_terminal]
                    conn.execute(
                        """UPDATE trade_intents SET status=?
                           WHERE intent_id = (SELECT intent_id FROM orders WHERE order_id=?)""",
                        (_intent_status, prow["order_id"]),
                    )
                    conn.commit()
                else:
                    # Unknown broker state — cannot safely recover; block submission
                    discrepancies.append(Discrepancy(
                        kind=DiscrepancyKind.RECONCILIATION_UNAVAILABLE,
                        subject=prow["order_id"],
                        local_value="PENDING_SUBMIT",
                        broker_value=_bstate,
                        detail=f"unknown broker state {_bstate!r} during PENDING_SUBMIT recovery",
                    ))
            else:
                # Broker definitively has no record — safe to cancel
                conn.execute(
                    "UPDATE orders SET state='CANCELLED', updated_at=? WHERE order_id=?",
                    (now_str, prow["order_id"]),
                )
                conn.execute(
                    """UPDATE trade_intents SET status='CANCELLED'
                       WHERE intent_id = (SELECT intent_id FROM orders WHERE order_id=?)""",
                    (prow["order_id"],),
                )
                conn.commit()

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
