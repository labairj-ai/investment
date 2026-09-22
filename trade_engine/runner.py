"""Standalone trade-runner script for AGENTIC_ALPACA_01 (0313, 0316, 0317, 0320).

Intended to be invoked by a systemd timer (trade-runner.service / trade-runner.timer).
Exit codes:
  0 — cycle completed, execution_state=OK
  1 — cycle completed, execution_state=HALTED (no orders submitted; safe)
  2 — unexpected exception or configuration error (call site should notify oncall)

Environment variables required:
  ALPACA_API_KEY
  ALPACA_API_SECRET
  ALPACA_PAPER_ACCOUNT_ID           required when ALPACA_PAPER_SUBMISSION_ENABLED=1
  ALPACA_PAPER_SUBMISSION_ENABLED   must be "1" to submit orders; any other value is dry-run
"""
from __future__ import annotations

import logging
import os
import socket
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parent.parent
_DB_PATH = _PROJECT_DIR / "out" / "investment.db"

if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger("trade_runner")

_ACCOUNT_ID = "AGENTIC_ALPACA_01"
_LEASE_TTL = 1800  # seconds — must exceed worst-case cycle duration (0317)


def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _broker_local_deltas(conn: sqlite3.Connection, adapter) -> tuple[float | None, float | None]:
    """Return (cash_delta, position_delta) = broker_value - local_value. None on error."""
    try:
        from trade_engine.broker_types import BrokerAccountState
        broker_state = adapter.get_broker_account(_ACCOUNT_ID)
        local_row = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id=?", (_ACCOUNT_ID,)
        ).fetchone()
        local_cash = float(local_row["current_cash"]) if local_row else 0.0
        cash_delta = broker_state.cash - local_cash

        broker_positions = {p.symbol: float(p.qty) for p in adapter.get_positions(_ACCOUNT_ID)}
        local_positions = {
            r["symbol"]: float(r["qty"])
            for r in conn.execute(
                "SELECT symbol, qty FROM position_snapshots WHERE account_id=?", (_ACCOUNT_ID,)
            ).fetchall()
        }
        all_symbols = set(broker_positions) | set(local_positions)
        total_pos_delta = sum(
            abs(broker_positions.get(s, 0.0) - local_positions.get(s, 0.0))
            for s in all_symbols
        )
        return cash_delta, total_pos_delta
    except Exception as exc:
        _log.warning("broker/local delta calculation failed: %s", exc)
        return None, None


def _oldest_unresolved_age_minutes(conn: sqlite3.Connection) -> float | None:
    """Return age in minutes of the oldest WORKING/PARTIALLY_FILLED order, or None."""
    try:
        row = conn.execute(
            """SELECT MIN(submitted_at) FROM orders
               WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')""",
            (_ACCOUNT_ID,),
        ).fetchone()
        oldest = row[0] if row else None
        if not oldest:
            return None
        from trade_engine.models import _parse_iso
        age = datetime.now(timezone.utc) - _parse_iso(oldest)
        return age.total_seconds() / 60.0
    except Exception as exc:
        _log.warning("oldest unresolved order age calculation failed: %s", exc)
        return None


def _write_cycle_run(conn: sqlite3.Connection, summary: dict, duration_seconds: float) -> None:
    oldest_age = _oldest_unresolved_age_minutes(conn)
    try:
        conn.execute(
            """INSERT INTO cycle_runs (
                account_id, run_at, execution_state, halt_reason,
                new_intents_processed, risk_rejections, orders_submitted,
                fills_applied, duplicate_fills_skipped, broker_api_errors,
                cash_delta_vs_broker, position_delta_vs_broker,
                duration_seconds, oldest_unresolved_order_age_minutes,
                broker_fills_observed, broker_fills_new,
                broker_fills_duplicate, external_fills_observed
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _ACCOUNT_ID,
                datetime.now(timezone.utc).isoformat(),
                summary.get("execution_state", "UNKNOWN"),
                summary.get("halt_reason"),
                summary.get("new_intents_processed", 0),
                summary.get("risk_rejections", 0),
                summary.get("new_orders_created", 0),
                summary.get("total_fills", 0),
                summary.get("duplicate_fills_skipped", 0),
                summary.get("broker_api_errors", 0),
                summary.get("cash_delta_vs_broker"),
                summary.get("position_delta_vs_broker"),
                duration_seconds,
                oldest_age,
                summary.get("broker_fills_observed", 0),
                summary.get("broker_fills_new", 0),
                summary.get("broker_fills_duplicate", 0),
                summary.get("external_fills_observed", 0),
            ),
        )
        conn.commit()
    except Exception as exc:
        _log.warning("failed to write cycle_runs row: %s", exc)


def _flush_broker_api_log(conn: sqlite3.Connection, adapter) -> None:
    calls = getattr(adapter, "_recent_api_calls", [])
    if not calls:
        return
    try:
        conn.executemany(
            """INSERT INTO broker_api_log
               (request_id, method, path, status_code, called_at, account_id, error_type)
               VALUES (:request_id, :method, :path, :status_code, :called_at, :account_id, :error_type)""",
            [{**c, "account_id": _ACCOUNT_ID, "error_type": c.get("error_type")} for c in calls],
        )
        conn.commit()
        adapter._recent_api_calls = []
    except Exception as exc:
        _log.warning("failed to flush broker_api_log: %s", exc)


def run() -> int:
    api_key = os.environ.get("ALPACA_API_KEY", "")
    api_secret = os.environ.get("ALPACA_API_SECRET", "")
    if not api_key or not api_secret:
        _log.error("ALPACA_API_KEY / ALPACA_API_SECRET not set — aborting")
        return 2

    submission_enabled = os.environ.get("ALPACA_PAPER_SUBMISSION_ENABLED") == "1"
    expected_account_id = os.environ.get("ALPACA_PAPER_ACCOUNT_ID") or None

    if submission_enabled and not expected_account_id:
        _log.error(
            "ALPACA_PAPER_SUBMISSION_ENABLED=1 but ALPACA_PAPER_ACCOUNT_ID is not set — "
            "account binding cannot be verified; aborting"
        )
        return 2

    if not submission_enabled:
        _log.warning(
            "ALPACA_PAPER_SUBMISSION_ENABLED != '1' — running in no-submit mode (risk + intent building only)"
        )

    from trade_engine.alpaca_adapter import AlpacaAdapter, _ALPACA_PAPER_URL, _ALPACA_DATA_URL
    from trade_engine.execution_engine import ExecutionSession, SessionNotReadyError
    from agent_db import acquire_execution_lease, release_execution_lease

    adapter = AlpacaAdapter(
        api_key=api_key,
        api_secret=api_secret,
        base_url=_ALPACA_PAPER_URL,
        data_url=_ALPACA_DATA_URL,
        submission_enabled=submission_enabled,
        expected_account_id=expected_account_id,
    )

    # ── Market-session gate (0325/0326) ──────────────────────────────────────
    # Fail-closed when submission is enabled: an unknown market state must not
    # allow order submission. Fail-open only when submission is disabled (dry-run),
    # where stale-quote circuit breakers provide a second line of defence.
    try:
        clock = adapter.get_market_clock()
        if not clock.get("is_open", True):
            _log.info(
                "SKIPPED_MARKET_CLOSED: market is closed (next_open=%s) — skipping cycle",
                clock.get("next_open", "unknown"),
            )
            _skipped_conn = _open_db(_DB_PATH)
            try:
                _skipped_conn.execute(
                    "INSERT INTO cycle_runs (account_id, run_at, execution_state, duration_seconds)"
                    " VALUES (?, ?, 'SKIPPED', 0.0)",
                    (_ACCOUNT_ID, datetime.now(timezone.utc).isoformat()),
                )
                _skipped_conn.commit()
            except Exception as exc:
                _log.warning("failed to write SKIPPED cycle_runs row: %s", exc)
            finally:
                _skipped_conn.close()
            return 0
    except Exception as exc:
        if submission_enabled:
            _log.error(
                "MARKET_CLOCK_UNAVAILABLE: clock check failed (%s) and submission is enabled — "
                "halting to prevent order submission with unknown market state",
                exc,
            )
            _halt_conn = _open_db(_DB_PATH)
            try:
                _halt_conn.execute(
                    "INSERT INTO cycle_runs (account_id, run_at, execution_state, halt_reason, duration_seconds)"
                    " VALUES (?, ?, 'HALTED', 'MARKET_CLOCK_UNAVAILABLE', 0.0)",
                    (_ACCOUNT_ID, datetime.now(timezone.utc).isoformat()),
                )
                _halt_conn.commit()
            except Exception as db_exc:
                _log.warning("failed to write HALTED cycle_runs row: %s", db_exc)
            finally:
                _halt_conn.close()
            return 1
        _log.warning("market clock check failed (%s) — proceeding with cycle (submission disabled)", exc)

    conn = _open_db(_DB_PATH)
    lease_holder = f"runner:{socket.gethostname()}:{os.getpid()}"

    if not acquire_execution_lease(conn, _ACCOUNT_ID, lease_holder, ttl_seconds=_LEASE_TTL):
        _log.error(
            "Execution lease for %s is held by another process — aborting to prevent concurrent execution",
            _ACCOUNT_ID,
        )
        conn.close()
        return 1

    summary: dict = {}
    duration_seconds: float = 0.0
    exit_code = 2
    started_at = time.monotonic()

    try:
        session = ExecutionSession(_ACCOUNT_ID, conn, broker=adapter)
        try:
            session.initialize()
        except SessionNotReadyError as exc:
            _log.error("SessionNotReadyError during initialize: %s", exc)
            duration_seconds = time.monotonic() - started_at
            broker_api_errors = sum(
                1 for c in getattr(adapter, "_recent_api_calls", [])
                if c.get("status_code") is None or c.get("status_code", 0) >= 400
            )
            summary = {
                "execution_state": "HALTED",
                "halt_reason": "NOT_TRADING_READY",
                "broker_api_errors": broker_api_errors,
            }
            exit_code = 1
            return exit_code

        summary = session.run_cycle()
        duration_seconds = time.monotonic() - started_at

        # ── Broker/local economic delta (0320) ────────────────────────────────
        cash_delta, pos_delta = _broker_local_deltas(conn, adapter)
        summary["cash_delta_vs_broker"] = cash_delta
        summary["position_delta_vs_broker"] = pos_delta

        # ── Broker API error count from adapter call log ──────────────────────
        # Count HTTP errors (status >= 400) AND transport failures (status_code=None) (0321).
        broker_api_errors = sum(
            1 for c in getattr(adapter, "_recent_api_calls", [])
            if c.get("status_code") is None or c.get("status_code", 0) >= 400
        )
        summary["broker_api_errors"] = broker_api_errors

        state = summary.get("execution_state", "UNKNOWN")
        _log.info(
            "cycle complete: state=%s duration=%.1fs intents=%d orders=%d fills=%d "
            "risk_rejections=%d duplicates_skipped=%d broker_api_errors=%d",
            state,
            duration_seconds,
            summary.get("new_intents_processed", 0),
            summary.get("new_orders_created", 0),
            summary.get("total_fills", 0),
            summary.get("risk_rejections", 0),
            summary.get("duplicate_fills_skipped", 0),
            broker_api_errors,
        )

        # Alert on economic divergence using same tolerances as reconciliation (0320, 0322).
        _CASH_TOLERANCE = 0.01
        _QTY_TOLERANCE = 0.0001
        if cash_delta is not None and abs(cash_delta) > _CASH_TOLERANCE:
            _log.error(
                "ECONOMIC DIVERGENCE: cash_delta_vs_broker=%.4f for %s — broker cash != local cash",
                cash_delta, _ACCOUNT_ID,
            )
        if pos_delta is not None and abs(pos_delta) > _QTY_TOLERANCE:
            _log.error(
                "ECONOMIC DIVERGENCE: position_delta_vs_broker=%.4f for %s — broker positions != local positions",
                pos_delta, _ACCOUNT_ID,
            )

        if state == "HALTED":
            _log.warning("cycle HALTED: %s", summary.get("halt_reason"))
            exit_code = 1
        elif state == "ERROR":
            _log.error("cycle ERROR: %s", summary.get("halt_reason"))
            exit_code = 2
        else:
            exit_code = 0
        return exit_code

    except Exception as exc:
        _log.exception("unexpected exception in trade runner: %s", exc)
        summary = {"execution_state": "ERROR", "halt_reason": str(exc)}
        duration_seconds = time.monotonic() - started_at
        exit_code = 2
        return exit_code

    finally:
        try:
            _write_cycle_run(conn, summary, duration_seconds)
        except Exception as exc:
            _log.warning("failed to write cycle_runs row: %s", exc)
        try:
            _flush_broker_api_log(conn, adapter)
        except Exception as exc:
            _log.warning("failed to flush broker_api_log: %s", exc)
        release_execution_lease(conn, _ACCOUNT_ID, lease_holder)
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
