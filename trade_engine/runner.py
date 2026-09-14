"""Standalone trade-runner script for AGENTIC_ALPACA_01 (0313, 0316).

Intended to be invoked by a systemd timer (trade-runner.service / trade-runner.timer).
Exit codes:
  0 — cycle completed, execution_state=OK
  1 — cycle completed, execution_state=HALTED (no orders submitted; safe)
  2 — unexpected exception (call site should notify oncall)

Environment variables required:
  ALPACA_API_KEY
  ALPACA_API_SECRET
  ALPACA_PAPER_SUBMISSION_ENABLED   must be "1" to submit orders; any other value is a dry run
  ALPACA_PAPER_ACCOUNT_ID           optional; enables broker account binding check
  TRADE_ENGINE_API_TOKEN            not used by runner.py directly (only needed by HTTP endpoint)
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parent.parent
_DB_PATH = _PROJECT_DIR / "out" / "investment.db"

# Ensure trade_engine package and project root are importable when run directly.
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger("trade_runner")


def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _write_cycle_run(conn: sqlite3.Connection, account_id: str, summary: dict) -> None:
    conn.execute(
        """INSERT INTO cycle_runs (
            account_id, run_at, execution_state, halt_reason,
            new_intents_processed, risk_rejections, orders_submitted,
            fills_applied, duplicate_fills_skipped, broker_api_errors,
            cash_delta_vs_broker, position_delta_vs_broker
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            account_id,
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
        ),
    )
    conn.commit()


def _flush_broker_api_log(conn: sqlite3.Connection, account_id: str, adapter) -> None:
    calls = getattr(adapter, "_recent_api_calls", [])
    if not calls:
        return
    conn.executemany(
        """INSERT INTO broker_api_log (request_id, method, path, status_code, called_at, account_id)
           VALUES (:request_id, :method, :path, :status_code, :called_at, :account_id)""",
        [{**c, "account_id": account_id} for c in calls],
    )
    conn.commit()
    adapter._recent_api_calls = []


def run() -> int:
    api_key = os.environ.get("ALPACA_API_KEY", "")
    api_secret = os.environ.get("ALPACA_API_SECRET", "")
    if not api_key or not api_secret:
        _log.error("ALPACA_API_KEY / ALPACA_API_SECRET not set — aborting")
        return 2

    submission_enabled = os.environ.get("ALPACA_PAPER_SUBMISSION_ENABLED") == "1"
    expected_account_id = os.environ.get("ALPACA_PAPER_ACCOUNT_ID") or None

    if not submission_enabled:
        _log.warning(
            "ALPACA_PAPER_SUBMISSION_ENABLED != '1' — running in no-submit mode (risk + intent building only)"
        )

    from trade_engine.alpaca_adapter import AlpacaAdapter, _ALPACA_PAPER_URL, _ALPACA_DATA_URL
    from trade_engine.execution_engine import ExecutionSession, SessionNotReadyError

    adapter = AlpacaAdapter(
        api_key=api_key,
        api_secret=api_secret,
        base_url=_ALPACA_PAPER_URL,
        data_url=_ALPACA_DATA_URL,
        submission_enabled=submission_enabled,
        expected_account_id=expected_account_id,
    )

    conn = _open_db(_DB_PATH)
    summary: dict = {}
    exit_code = 2

    try:
        session = ExecutionSession("AGENTIC_ALPACA_01", conn, broker=adapter)
        try:
            session.initialize()
        except SessionNotReadyError as exc:
            _log.error("SessionNotReadyError during initialize: %s", exc)
            summary = {"execution_state": "HALTED", "halt_reason": "NOT_TRADING_READY"}
            exit_code = 1
            return exit_code

        summary = session.run_cycle()
        state = summary.get("execution_state", "UNKNOWN")
        _log.info(
            "cycle complete: state=%s intents=%d orders=%d fills=%d risk_rejections=%d",
            state,
            summary.get("new_intents_processed", 0),
            summary.get("new_orders_created", 0),
            summary.get("total_fills", 0),
            summary.get("risk_rejections", 0),
        )
        if state == "HALTED":
            _log.warning("cycle HALTED: %s", summary.get("halt_reason"))
            exit_code = 1
        else:
            exit_code = 0
        return exit_code

    except Exception as exc:
        _log.exception("unexpected exception in trade runner: %s", exc)
        summary = {"execution_state": "ERROR", "halt_reason": str(exc)}
        exit_code = 2
        return exit_code

    finally:
        try:
            _write_cycle_run(conn, "AGENTIC_ALPACA_01", summary)
        except Exception as exc:
            _log.warning("failed to write cycle_runs row: %s", exc)
        try:
            _flush_broker_api_log(conn, "AGENTIC_ALPACA_01", adapter)
        except Exception as exc:
            _log.warning("failed to flush broker_api_log: %s", exc)
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
