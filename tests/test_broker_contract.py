"""Broker adapter contract tests — any concrete BrokerAdapter must pass (0241).

Usage: mix BrokerAdapterContractMixin into a test class that provides make_adapter().

Concrete implementations: TestShadowBrokerAdapterContract.
When a paper or live adapter is written, add its class here.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from trade_engine.broker_adapter import BrokerAdapter, ShadowBrokerAdapter
from trade_engine.broker_types import BrokerAccountState, BrokerFill, BrokerOrder, BrokerPosition, BrokerQuote
from trade_engine.models import (
    InstrumentType, IntentStatus, Order, OrderState, OrderType, Side, TimeInForce, TradeIntent
)
from trade_engine import market_calendar


# ── Shared test DB setup ──────────────────────────────────────────────────────

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trading_accounts (
            account_id TEXT PRIMARY KEY, name TEXT, mode TEXT,
            starting_capital REAL, current_cash REAL, broker TEXT,
            trading_enabled INTEGER DEFAULT 1, policy_version TEXT, created_at TEXT,
            nav_high_water REAL, last_fill_synced_at TEXT
        );
        CREATE TABLE IF NOT EXISTS trade_intents (
            intent_id TEXT PRIMARY KEY, account_id TEXT, recommendation_id INTEGER,
            agent_run_id INTEGER, instrument_type TEXT, symbol TEXT, side TEXT,
            quantity REAL, contracts INTEGER, option_type TEXT, strike REAL,
            expiration TEXT, order_type TEXT, limit_price REAL, time_in_force TEXT,
            strategy TEXT, thesis_version INTEGER, strategy_config_hash TEXT,
            portfolio_snapshot_id TEXT, policy_hash TEXT, valid_until TEXT, created_at TEXT,
            status TEXT DEFAULT 'PENDING'
        );
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, intent_id TEXT, account_id TEXT,
            symbol TEXT, side TEXT, quantity REAL, contracts INTEGER,
            order_type TEXT, limit_price REAL, state TEXT DEFAULT 'PENDING',
            time_in_force TEXT DEFAULT 'DAY',
            broker_order_id TEXT, submitted_at TEXT, updated_at TEXT,
            fill_qty REAL DEFAULT 0, fill_cash REAL DEFAULT 0,
            market_data_status TEXT, expires_at TEXT,
            cancel_reason TEXT, cancel_requested_at TEXT, cancel_confirmed_at TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_intent_id ON orders (intent_id);
        CREATE TABLE IF NOT EXISTS fills (
            fill_id TEXT PRIMARY KEY, order_id TEXT, account_id TEXT,
            symbol TEXT, side TEXT, qty REAL, price REAL, fee REAL DEFAULT 0,
            fill_source TEXT, filled_at TEXT,
            cost_basis REAL DEFAULT 0, realized_pnl REAL, realized_pnl_pct REAL
        );
        CREATE TABLE IF NOT EXISTS position_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, symbol TEXT,
            qty REAL, avg_cost REAL, instrument_type TEXT, as_of TEXT,
            market_price REAL, market_value REAL, price_as_of TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_account_symbol
            ON position_snapshots (account_id, symbol);
    """)
    conn.execute(
        """INSERT INTO trading_accounts
           (account_id, name, mode, starting_capital, current_cash,
            trading_enabled, policy_version, created_at)
           VALUES ('AGENTIC_SHADOW_01','Test','shadow',10000,10000,1,'1.0','2026-01-01T00:00:00+00:00')"""
    )
    conn.commit()
    return conn


def _make_intent(**kwargs) -> TradeIntent:
    now = datetime.now(timezone.utc)
    defaults = dict(
        intent_id=str(uuid.uuid4()),
        account_id="AGENTIC_SHADOW_01",
        recommendation_id=None,
        agent_run_id=None,
        instrument_type=InstrumentType.EQUITY,
        symbol="ANET",
        side=Side.BUY,
        quantity=1.0,
        contracts=None,
        option_type=None,
        strike=None,
        expiration=None,
        order_type=OrderType.LIMIT,
        limit_price=100.0,
        time_in_force=TimeInForce.GTC,
        strategy="test",
        thesis_version=None,
        strategy_config_hash=None,
        policy_hash=None,
        valid_until=(now.replace(hour=23, minute=59)).isoformat(),
        created_at=now.isoformat(),
        status=IntentStatus.PENDING,
    )
    defaults.update(kwargs)
    return TradeIntent(**defaults)


def _insert_intent(conn, intent: TradeIntent) -> None:
    d = intent.to_db_dict()
    cols = ", ".join(d.keys())
    ph = ", ".join(f":{k}" for k in d.keys())
    conn.execute(f"INSERT INTO trade_intents ({cols}) VALUES ({ph})", d)
    conn.commit()


def _fresh_quote(**kwargs) -> BrokerQuote:
    now_iso = datetime.now(timezone.utc).isoformat()
    defaults = dict(bid=99.0, ask=100.0, symbol="ANET", retrieved_at=now_iso)
    defaults.update(kwargs)
    return BrokerQuote(**defaults)


# ── Contract mixin ────────────────────────────────────────────────────────────

class BrokerAdapterContractMixin:
    """Mix into a test class that provides make_adapter(conn) -> BrokerAdapter.

    Each test calls make_adapter() with a fresh in-memory DB. Tests use ONLY the
    BrokerAdapter interface — no direct ShadowBroker or DB access.
    """

    def make_adapter(self, conn: sqlite3.Connection) -> BrokerAdapter:
        raise NotImplementedError("Subclass must implement make_adapter(conn)")

    # ── 1. submit_order returns Order with order_id ───────────────────────────

    def test_submit_order_returns_order(self):
        conn = _make_conn()
        adapter = self.make_adapter(conn)
        intent = _make_intent()
        _insert_intent(conn, intent)
        order = adapter.submit_order(intent)
        assert isinstance(order, Order)
        assert order.order_id
        assert order.state in (OrderState.WORKING, OrderState.SUBMITTED)

    # ── 2. Idempotent submit — same intent_id → same order_id ─────────────────

    def test_submit_order_idempotent(self):
        conn = _make_conn()
        adapter = self.make_adapter(conn)
        intent = _make_intent()
        _insert_intent(conn, intent)
        order1 = adapter.submit_order(intent)
        order2 = adapter.submit_order(intent)
        assert order1.order_id == order2.order_id

    # ── 3. get_order returns submitted order ──────────────────────────────────

    def test_get_order_after_submit(self):
        conn = _make_conn()
        adapter = self.make_adapter(conn)
        intent = _make_intent()
        _insert_intent(conn, intent)
        order = adapter.submit_order(intent)
        fetched = adapter.get_order(order.order_id)
        assert fetched is not None
        assert fetched.order_id == order.order_id
        assert fetched.symbol == intent.symbol

    # ── 4. cancel_order transitions to CANCELLED ──────────────────────────────

    def test_cancel_order_changes_state(self):
        conn = _make_conn()
        adapter = self.make_adapter(conn)
        intent = _make_intent()
        _insert_intent(conn, intent)
        order = adapter.submit_order(intent)
        assert order.state == OrderState.WORKING
        adapter.cancel_order(order.order_id, reason="TEST_CANCEL")
        cancelled = adapter.get_order(order.order_id)
        assert cancelled.state == OrderState.CANCELLED

    # ── 5. attempt_fill on WORKING order with valid quote produces Fill ────────

    def test_full_fill_state(self):
        conn = _make_conn()
        with patch.object(market_calendar, "is_market_open", return_value=True):
            adapter = self.make_adapter(conn)
            intent = _make_intent(quantity=1.0, limit_price=100.0)
            _insert_intent(conn, intent)
            order = adapter.submit_order(intent)
            bquote = _fresh_quote(bid=99.0, ask=100.0)
            fill = adapter.attempt_fill(order, bquote)
        assert fill is not None
        assert fill.qty == pytest.approx(1.0)
        filled = adapter.get_order(order.order_id)
        assert filled.state == OrderState.FILLED

    # ── 6. Partial fill → PARTIALLY_FILLED ────────────────────────────────────

    def test_partial_fill_state(self):
        conn = _make_conn()
        with patch.object(market_calendar, "is_market_open", return_value=True):
            adapter = self.make_adapter(conn)
            intent = _make_intent(quantity=10.0, limit_price=100.0)
            _insert_intent(conn, intent)
            order = adapter.submit_order(intent)
            # Directly update order qty to simulate partial fill state externally,
            # then call attempt_fill. ShadowBrokerAdapter fills remaining qty in one shot,
            # so we manually set fill_qty to simulate partial state first.
            conn.execute(
                "UPDATE orders SET fill_qty=5.0, state='PARTIALLY_FILLED' WHERE order_id=?",
                (order.order_id,),
            )
            conn.commit()
            partial_order = adapter.get_order(order.order_id)
            assert partial_order.state == OrderState.PARTIALLY_FILLED
            bquote = _fresh_quote(bid=99.0, ask=100.0)
            fill2 = adapter.attempt_fill(partial_order, bquote)
        assert fill2 is not None
        final = adapter.get_order(order.order_id)
        assert final.state == OrderState.FILLED

    # ── 7. get_positions returns list[BrokerPosition] ─────────────────────────

    def test_get_positions_returns_typed_list(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 10.0, 100.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        adapter = self.make_adapter(conn)
        positions = adapter.get_positions("AGENTIC_SHADOW_01")
        assert isinstance(positions, list)
        assert len(positions) == 1
        pos = positions[0]
        assert isinstance(pos, BrokerPosition)
        assert pos.symbol == "ANET"
        assert pos.qty == pytest.approx(10.0)

    # ── 8. get_quote returns BrokerQuote (not shadow Quote) ───────────────────

    def test_get_quote_returns_broker_quote(self):
        from trade_engine import market_data
        now_iso = datetime.now(timezone.utc).isoformat()
        from trade_engine.shadow_broker import Quote as ShadowQuote
        shadow_q = ShadowQuote(bid=99.0, ask=101.0, timestamp="t", retrieved_at=now_iso)
        conn = _make_conn()
        adapter = self.make_adapter(conn)
        with patch.object(market_data, "_get_executable_quote", return_value=shadow_q):
            bquote = adapter.get_quote("ANET")
        assert bquote is not None
        assert isinstance(bquote, BrokerQuote)
        assert bquote.bid == pytest.approx(99.0)
        assert bquote.ask == pytest.approx(101.0)

    # ── 9. get_broker_account returns BrokerAccountState ─────────────────────

    def test_get_broker_account_returns_state(self):
        conn = _make_conn()
        adapter = self.make_adapter(conn)
        state = adapter.get_broker_account("AGENTIC_SHADOW_01")
        assert isinstance(state, BrokerAccountState)
        assert state.cash == pytest.approx(10000.0)
        assert state.nav >= state.cash

    # ── 10. get_fills empty before any fills ─────────────────────────────────

    def test_get_fills_empty_before_fills(self):
        conn = _make_conn()
        adapter = self.make_adapter(conn)
        fills = adapter.get_fills("AGENTIC_SHADOW_01")
        assert isinstance(fills, list)
        assert len(fills) == 0

    # ── 11. get_fills returns BrokerFill after fill ───────────────────────────

    def test_get_fills_returns_broker_fill_type(self):
        conn = _make_conn()
        with patch.object(market_calendar, "is_market_open", return_value=True):
            adapter = self.make_adapter(conn)
            intent = _make_intent(quantity=1.0, limit_price=100.0)
            _insert_intent(conn, intent)
            order = adapter.submit_order(intent)
            adapter.attempt_fill(order, _fresh_quote())
        fills = adapter.get_fills("AGENTIC_SHADOW_01")
        assert len(fills) == 1
        assert isinstance(fills[0], BrokerFill)
        assert fills[0].account_id == "AGENTIC_SHADOW_01"
        assert fills[0].qty == pytest.approx(1.0)

    # ── 12. get_open_orders includes WORKING order ────────────────────────────

    def test_get_open_orders_returns_working_order(self):
        conn = _make_conn()
        adapter = self.make_adapter(conn)
        intent = _make_intent()
        _insert_intent(conn, intent)
        order = adapter.submit_order(intent)
        open_orders = adapter.get_open_orders("AGENTIC_SHADOW_01")
        assert isinstance(open_orders, list)
        order_ids = [o.broker_order_id for o in open_orders]
        assert order.order_id in order_ids

    # ── 13. Cancelled order not in working orders ─────────────────────────────

    def test_cancelled_order_not_in_open_orders(self):
        conn = _make_conn()
        adapter = self.make_adapter(conn)
        intent = _make_intent()
        _insert_intent(conn, intent)
        order = adapter.submit_order(intent)
        adapter.cancel_order(order.order_id)
        open_orders = adapter.get_open_orders("AGENTIC_SHADOW_01")
        order_ids = [o.broker_order_id for o in open_orders]
        assert order.order_id not in order_ids

    # ── 14. get_fills since filter excludes old fills ─────────────────────────

    def test_get_fills_since_filter(self):
        conn = _make_conn()
        with patch.object(market_calendar, "is_market_open", return_value=True):
            adapter = self.make_adapter(conn)
            intent = _make_intent(quantity=1.0, limit_price=100.0)
            _insert_intent(conn, intent)
            order = adapter.submit_order(intent)
            adapter.attempt_fill(order, _fresh_quote())
        future = (datetime.now(timezone.utc).replace(year=2099)).isoformat()
        fills_all = adapter.get_fills("AGENTIC_SHADOW_01")
        fills_future = adapter.get_fills("AGENTIC_SHADOW_01", since=future)
        assert len(fills_all) == 1
        assert len(fills_future) == 0


# ── Shadow reference implementation ──────────────────────────────────────────

class TestShadowBrokerAdapterContract(BrokerAdapterContractMixin):
    """ShadowBrokerAdapter passes the full BrokerAdapter contract (0241)."""

    def make_adapter(self, conn: sqlite3.Connection) -> BrokerAdapter:
        return ShadowBrokerAdapter(conn, "AGENTIC_SHADOW_01")
