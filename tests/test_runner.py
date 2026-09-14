"""Tests for trade_engine/runner.py — 0324 (halt telemetry) and 0325 (market gate).

AlpacaAdapter, ExecutionSession, acquire_execution_lease are all imported inside
runner.run() so they must be patched at the source module, not on trade_engine.runner.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cycle_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    run_at TEXT,
    execution_state TEXT,
    halt_reason TEXT,
    new_intents_processed INTEGER DEFAULT 0,
    risk_rejections INTEGER DEFAULT 0,
    orders_submitted INTEGER DEFAULT 0,
    fills_applied INTEGER DEFAULT 0,
    duplicate_fills_skipped INTEGER DEFAULT 0,
    broker_api_errors INTEGER DEFAULT 0,
    cash_delta_vs_broker REAL,
    position_delta_vs_broker REAL,
    duration_seconds REAL DEFAULT 0.0,
    oldest_unresolved_order_age_minutes REAL
);
CREATE TABLE IF NOT EXISTS broker_api_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    method TEXT,
    path TEXT,
    status_code INTEGER,
    called_at TEXT,
    account_id TEXT,
    error_type TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    state TEXT,
    submitted_at TEXT
);
CREATE TABLE IF NOT EXISTS execution_leases (
    account_id TEXT PRIMARY KEY,
    holder TEXT,
    acquired_at TEXT,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS trading_accounts (
    account_id TEXT PRIMARY KEY,
    current_cash REAL DEFAULT 0.0,
    nav_high_water REAL,
    last_fill_synced_at TEXT
);
CREATE TABLE IF NOT EXISTS position_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    symbol TEXT,
    qty REAL,
    market_price REAL,
    market_value REAL,
    price_as_of TEXT
);
"""


def _setup_temp_db() -> str:
    """Create a temp DB file with the trade-engine schema; return the file path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.close()
    return path


def _query_db(path: str, sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def _patch_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")


# ── 0325: market-session gate ─────────────────────────────────────────────────

class TestMarketGate:
    def test_market_closed_returns_0_and_writes_skipped_row(self, monkeypatch, tmp_path):
        """Market closed → exit 0, SKIPPED cycle_runs row, no lease acquired."""
        _patch_env(monkeypatch)
        db_path = _setup_temp_db()

        with (
            patch("trade_engine.runner._DB_PATH", Path(db_path)),
            patch("trade_engine.alpaca_adapter.AlpacaAdapter") as MockAdapter,
            patch("agent_db.acquire_execution_lease") as mock_acquire,
        ):
            adapter_inst = MockAdapter.return_value
            adapter_inst.get_market_clock.return_value = {
                "is_open": False,
                "next_open": "2026-09-15T13:30:00Z",
                "next_close": "",
            }

            from trade_engine import runner
            result = runner.run()

        assert result == 0
        mock_acquire.assert_not_called()
        rows = _query_db(db_path, "SELECT execution_state FROM cycle_runs")
        assert len(rows) == 1
        assert rows[0]["execution_state"] == "SKIPPED"

    def test_market_open_proceeds_to_lease(self, monkeypatch):
        """Market open → does NOT return early; proceeds to lease acquisition."""
        _patch_env(monkeypatch)
        db_path = _setup_temp_db()

        with (
            patch("trade_engine.runner._DB_PATH", Path(db_path)),
            patch("trade_engine.alpaca_adapter.AlpacaAdapter") as MockAdapter,
            patch("agent_db.acquire_execution_lease", return_value=False) as mock_acquire,
            patch("agent_db.release_execution_lease"),
        ):
            adapter_inst = MockAdapter.return_value
            adapter_inst.get_market_clock.return_value = {
                "is_open": True,
                "next_open": "",
                "next_close": "2026-09-14T20:00:00Z",
            }

            from trade_engine import runner
            result = runner.run()

        # Lease refused → exit 1; the key assertion is that acquire WAS called
        mock_acquire.assert_called_once()
        assert result == 1

    def test_clock_failure_fails_open(self, monkeypatch):
        """Clock check exception → proceed (fail-open), reach lease acquisition."""
        _patch_env(monkeypatch)
        db_path = _setup_temp_db()

        with (
            patch("trade_engine.runner._DB_PATH", Path(db_path)),
            patch("trade_engine.alpaca_adapter.AlpacaAdapter") as MockAdapter,
            patch("agent_db.acquire_execution_lease", return_value=False) as mock_acquire,
            patch("agent_db.release_execution_lease"),
        ):
            adapter_inst = MockAdapter.return_value
            adapter_inst.get_market_clock.side_effect = RuntimeError("unreachable")

            from trade_engine import runner
            runner.run()

        # Clock failed but we still attempted the lease (fail-open behaviour)
        mock_acquire.assert_called_once()


# ── 0324: halt telemetry ──────────────────────────────────────────────────────

class TestHaltTelemetry:
    def test_session_not_ready_writes_duration_and_api_errors(self, monkeypatch):
        """SessionNotReadyError path records real duration_seconds and broker_api_errors."""
        _patch_env(monkeypatch)
        db_path = _setup_temp_db()

        from trade_engine.execution_engine import SessionNotReadyError

        with (
            patch("trade_engine.runner._DB_PATH", Path(db_path)),
            patch("trade_engine.alpaca_adapter.AlpacaAdapter") as MockAdapter,
            patch("agent_db.acquire_execution_lease", return_value=True),
            patch("agent_db.release_execution_lease"),
            patch("trade_engine.execution_engine.ExecutionSession") as MockSession,
        ):
            adapter_inst = MockAdapter.return_value
            adapter_inst.get_market_clock.return_value = {"is_open": True}
            # Simulate a transport failure recorded before SessionNotReadyError
            adapter_inst._recent_api_calls = [
                {
                    "method": "GET",
                    "path": "/v2/account",
                    "status_code": None,
                    "request_id": "",
                    "called_at": "2026-09-14T12:00:00+00:00",
                    "error_type": "ConnectionError",
                }
            ]

            session_inst = MockSession.return_value
            session_inst.initialize.side_effect = SessionNotReadyError("broker unreachable")

            from trade_engine import runner
            result = runner.run()

        assert result == 1
        rows = _query_db(db_path, "SELECT * FROM cycle_runs")
        assert len(rows) == 1
        row = rows[0]
        assert row["execution_state"] == "HALTED"
        assert row["halt_reason"] == "NOT_TRADING_READY"
        # duration_seconds must be positive (real elapsed time recorded before return)
        assert row["duration_seconds"] > 0.0
        # broker_api_errors reflects the transport failure (status_code=None → counts as error)
        assert row["broker_api_errors"] == 1
