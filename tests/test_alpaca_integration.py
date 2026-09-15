"""End-to-end paper integration tests (0296).

These tests hit the real Alpaca paper endpoint. Required environment variables:
  ALPACA_API_KEY       — Alpaca paper API key
  ALPACA_API_SECRET    — Alpaca paper API secret

For order submission tests additionally require (0300):
  ALPACA_INTEGRATION_SUBMIT=1   — must be exactly "1"; "0" or any other value skips
  ALPACA_EXPECTED_ACCOUNT_ID    — the paper account ID to bind the adapter to

For the marketable-fill test additionally require:
  ALPACA_INTEGRATION_FILL=1     — must be exactly "1"; only set during market hours

Mark: pytest.mark.integration — skipped in CI unless credentials are present.

Execution order (0296 four-phase plan):
  Phase 1: Read-only binding — credentials, balances, positions, fills, quote, initialize()
  Phase 2: Go/no-go matrix  — idempotent fills, account ID, crash-after-submit recovery
  Phase 3: Live order round-trip — non-marketable submit/cancel, marketable fill + restart replay
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from unittest.mock import patch

import pytest

from trade_engine.alpaca_adapter import AlpacaAdapter, _ALPACA_PAPER_URL, _ALPACA_DATA_URL
from trade_engine.policy import TradingPolicy

# ── Skip guards ───────────────────────────────────────────────────────────────

_KEY = os.environ.get("ALPACA_API_KEY")
_SECRET = os.environ.get("ALPACA_API_SECRET")
_HAVE_CREDS = bool(_KEY and _SECRET)

integration = pytest.mark.integration
skip_no_creds = pytest.mark.skipif(
    not _HAVE_CREDS,
    reason="ALPACA_API_KEY / ALPACA_API_SECRET not set — skipping live integration tests",
)


def _make_adapter(submission_enabled: bool = False) -> AlpacaAdapter:
    assert _KEY and _SECRET, "Credentials required"
    expected_account_id = os.environ.get("ALPACA_EXPECTED_ACCOUNT_ID") or None
    return AlpacaAdapter(
        api_key=_KEY,
        api_secret=_SECRET,
        base_url=_ALPACA_PAPER_URL,
        data_url=_ALPACA_DATA_URL,
        submission_enabled=submission_enabled,
        expected_account_id=expected_account_id,
    )


# ── Shared DB + policy helpers ────────────────────────────────────────────────

_SCHEMA_SQL = """
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
    CREATE TABLE IF NOT EXISTS risk_decisions (
        decision_id INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT,
        decision TEXT, checks_json TEXT, evaluated_at TEXT,
        uuid_id TEXT, policy_version TEXT, policy_hash TEXT,
        account_cash_at_eval REAL, account_nav_at_eval REAL, phase TEXT
    );
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY, intent_id TEXT, account_id TEXT,
        symbol TEXT, side TEXT, quantity REAL, contracts INTEGER,
        order_type TEXT, limit_price REAL, state TEXT DEFAULT 'PENDING',
        time_in_force TEXT DEFAULT 'DAY',
        broker_order_id TEXT, client_order_id TEXT, submitted_at TEXT, updated_at TEXT,
        fill_qty REAL DEFAULT 0, fill_cash REAL DEFAULT 0,
        market_data_status TEXT, expires_at TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_intent_id ON orders (intent_id);
    CREATE TABLE IF NOT EXISTS fills (
        fill_id TEXT PRIMARY KEY, order_id TEXT, account_id TEXT,
        symbol TEXT, side TEXT, qty REAL, price REAL, fee REAL DEFAULT 0,
        fill_source TEXT, filled_at TEXT,
        cost_basis REAL DEFAULT 0, realized_pnl REAL, realized_pnl_pct REAL
    );
    CREATE TABLE IF NOT EXISTS account_snapshots (
        snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT,
        cash REAL, nav REAL, buying_power REAL, snapshot_at TEXT,
        gross_exposure REAL, reserved_cash REAL, open_order_notional REAL,
        realized_pnl_today REAL, unrealized_pnl REAL, snapshot_reason TEXT
    );
    CREATE TABLE IF NOT EXISTS position_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, symbol TEXT,
        qty REAL, avg_cost REAL, instrument_type TEXT, as_of TEXT,
        market_price REAL, market_value REAL, price_as_of TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_account_symbol
        ON position_snapshots (account_id, symbol);
    CREATE TABLE IF NOT EXISTS option_quote_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, strike REAL,
        expiration TEXT, iv REAL, bid REAL, ask REAL, spread_pct REAL, captured_at REAL
    );
    CREATE TABLE IF NOT EXISTS event_calendar (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, event_type TEXT, event_date TEXT
    );
    CREATE TABLE IF NOT EXISTS recommendations (
        id INTEGER PRIMARY KEY, run_id INTEGER, ticker TEXT NOT NULL,
        action TEXT NOT NULL, action_payload_json TEXT,
        recommendation_score INTEGER DEFAULT 50, confidence INTEGER DEFAULT 50,
        priority TEXT DEFAULT 'normal', why_now TEXT, rationale TEXT,
        counter_case TEXT, no_action_case TEXT,
        status TEXT DEFAULT 'open', valid_until REAL, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS executed_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recommendation_id INTEGER, ticker TEXT NOT NULL,
        action TEXT NOT NULL, quantity REAL, execution_price REAL,
        execution_date TEXT NOT NULL, fees REAL NOT NULL DEFAULT 0,
        strike REAL, expiration TEXT, premium REAL, contracts INTEGER,
        tax_lot_ids TEXT, notes TEXT, source TEXT NOT NULL DEFAULT 'manual',
        created_at REAL NOT NULL DEFAULT 0,
        position_shares_before REAL, position_shares_after REAL,
        execution_fraction REAL,
        fill_id TEXT,
        UNIQUE(fill_id)
    );
    CREATE TABLE IF NOT EXISTS investment_theses (id INTEGER PRIMARY KEY, ticker TEXT);
"""


def _make_integration_conn(account_id: str, cash: float = 100_000.0) -> sqlite3.Connection:
    """In-memory DB with full engine schema and a seeded paper trading account."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO trading_accounts "
        "(account_id, name, mode, starting_capital, current_cash, broker, policy_version, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (account_id, "Integration", "PAPER", cash, cash, "alpaca", "1.0", "2026-09-14T00:00:00Z"),
    )
    conn.commit()
    return conn


def _permissive_policy(account_id: str) -> TradingPolicy:
    """Permissive paper-trading policy for the given account_id — used in integration tests."""
    raw = json.dumps({
        "policy_version": "1.0", "account_id": account_id,
        "capital": {"starting_capital": 100000, "minimum_cash_pct": 1, "minimum_cash_abs": 100},
        "equities": {"buy_allowed": True, "sell_allowed": True, "shorting_allowed": False,
                     "max_single_position_pct": 50, "max_new_position_pct": 20},
        "options": {"covered_calls_allowed": False, "naked_options_allowed": False, "max_contracts_per_symbol": 0},
        "execution": {"market_orders_allowed": False, "max_orders_per_day": 100,
                      "max_daily_notional_pct": 99, "max_slippage_pct": 5.0, "min_limit_price": 0.01},
        "risk": {"max_drawdown_pct": 50, "max_daily_loss_pct": 50, "max_weekly_loss_pct": 50},
        "circuit_breakers": {"trading_enabled": True, "halt_on_position_mismatch": False,
                             "halt_on_data_stale_minutes": 1440, "halt_on_daily_loss_pct": 50},
    })
    return TradingPolicy(
        policy_version="1.0", account_id=account_id,
        capital={"starting_capital": 100000, "minimum_cash_pct": 1, "minimum_cash_abs": 100},
        equities={"buy_allowed": True, "sell_allowed": True, "shorting_allowed": False,
                  "max_single_position_pct": 50, "max_new_position_pct": 20},
        options={"covered_calls_allowed": False, "naked_options_allowed": False, "max_contracts_per_symbol": 0},
        execution={"market_orders_allowed": False, "max_orders_per_day": 100,
                   "max_daily_notional_pct": 99, "max_slippage_pct": 5.0, "min_limit_price": 0.01},
        risk={"max_drawdown_pct": 50, "max_daily_loss_pct": 50, "max_weekly_loss_pct": 50},
        circuit_breakers={"trading_enabled": True, "halt_on_position_mismatch": False,
                          "halt_on_data_stale_minutes": 1440, "halt_on_daily_loss_pct": 50},
        _raw_json=raw,
    )


# ── Phase 1: Read-only binding ────────────────────────────────────────────────

@integration
@skip_no_creds
class TestReadOnlyBinding:
    def test_get_account_id_returns_string(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        assert isinstance(account_id, str) and len(account_id) > 0

    def test_get_broker_account_has_positive_values(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        state = adapter.get_broker_account(account_id)
        assert state.account_id == account_id
        assert state.cash > 0
        assert state.nav > 0
        assert state.buying_power >= 0

    def test_get_positions_returns_list(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        positions = adapter.get_positions(account_id)
        assert isinstance(positions, list)
        for p in positions:
            assert isinstance(p.symbol, str)
            assert p.qty > 0

    def test_get_open_orders_returns_list(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        orders = adapter.get_open_orders(account_id)
        assert isinstance(orders, list)

    def test_get_fills_returns_list(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        fills = adapter.get_fills(account_id)
        assert isinstance(fills, list)
        # All fills should carry the account_id (0298)
        for f in fills:
            assert f.account_id == account_id

    def test_get_quote_aapl_returns_valid_quote(self):
        adapter = _make_adapter()
        quote = adapter.get_quote("AAPL")
        assert quote is not None
        assert quote.symbol == "AAPL"
        # bid or ask may be 0 outside market hours; assert at least one is positive
        assert quote.bid > 0 or quote.ask > 0, f"both bid and ask are 0 — adapter may be broken"
        if quote.ask > 0 and quote.bid > 0:
            assert quote.ask >= quote.bid

    def test_initialize_trading_session_reaches_trading_ready(self):
        """initialize_trading_session() with a clean paper account → TRADING_READY (0296 Phase 1)."""
        from trade_engine import execution_engine
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        conn = _make_integration_conn(account_id)
        policy = _permissive_policy(account_id)
        with patch("trade_engine.execution_engine.load_policy", return_value=policy):
            state = execution_engine.initialize_trading_session(account_id, conn, broker=adapter)
        assert state == execution_engine.TradingReadyState.TRADING_READY


# ── Phase 2: Go/no-go matrix ──────────────────────────────────────────────────

@integration
@skip_no_creds
class TestGoNoGoMatrix:
    def test_get_fills_idempotent(self):
        """Matrix point 4: duplicate fill replay — same fill IDs returned on two calls."""
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        fills_first = adapter.get_fills(account_id)
        fills_second = adapter.get_fills(account_id)
        ids_first = {f.broker_fill_id for f in fills_first}
        ids_second = {f.broker_fill_id for f in fills_second}
        assert ids_first == ids_second

    def test_fill_account_id_never_none(self):
        """Matrix point 5: all fills carry account_id so apply_broker_fill() will pass (0298)."""
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        fills = adapter.get_fills(account_id)
        for f in fills:
            assert f.account_id is not None, f"fill {f.broker_fill_id} has account_id=None"

    def test_poll_order_events_seeds_from_open_orders(self):
        """Matrix point 1 (adapter level): poll_order_events() seeds correctly from broker on first call."""
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        # First call seeds; subsequent call refreshes. With no tracked orders, should return [].
        events = adapter.poll_order_events(account_id)
        assert isinstance(events, list)
        assert adapter._poll_seeded is True


# ── Phase 3: Live order tests ─────────────────────────────────────────────────

@integration
@skip_no_creds
class TestLiveOrderRoundTrip:
    """1-share DAY LIMIT order: submit → WORKING → cancel → CANCELLED.

    Requires ALPACA_INTEGRATION_SUBMIT=1 (exactly) and ALPACA_EXPECTED_ACCOUNT_ID (0300).
    """

    @pytest.fixture(autouse=True)
    def require_submit_flag(self):
        if os.environ.get("ALPACA_INTEGRATION_SUBMIT") != "1":
            pytest.skip("ALPACA_INTEGRATION_SUBMIT != '1' — skipping order submission tests")
        if not os.environ.get("ALPACA_EXPECTED_ACCOUNT_ID"):
            pytest.skip("ALPACA_EXPECTED_ACCOUNT_ID not set — required for submission tests (0300)")

    def test_submit_limit_below_market_then_cancel(self):
        """Phase 3: submit non-marketable 1-share order → WORKING → cancel → CANCELLED."""
        from trade_engine.models import TradeIntent, Side, InstrumentType, OrderType, TimeInForce
        adapter = _make_adapter(submission_enabled=True)
        account_id = adapter.get_account_id()

        quote = adapter.get_quote("AAPL")
        assert quote is not None
        far_below = round(quote.bid * 0.90, 2)

        client_id = f"test-{uuid.uuid4().hex[:8]}"
        intent = TradeIntent(
            intent_id="integration-test",
            account_id=account_id,
            recommendation_id=None,
            agent_run_id=None,
            instrument_type=InstrumentType.EQUITY,
            symbol="AAPL",
            side=Side.BUY,
            quantity=1.0,
            contracts=None,
            option_type=None,
            strike=None,
            expiration=None,
            order_type=OrderType.LIMIT,
            limit_price=far_below,
            time_in_force=TimeInForce.DAY,
            strategy="integration-test",
            thesis_version=None,
            strategy_config_hash=None,
            policy_hash=None,
            valid_until="2099-12-31T23:59:59Z",
            created_at="2026-09-14T00:00:00Z",
        )

        ack = adapter.submit_order(intent, client_order_id=client_id)
        assert ack.broker_order_id
        assert ack.normalized_state in ("WORKING", "PARTIALLY_FILLED")

        time.sleep(1)

        # Matrix point 3: crash recovery — fresh adapter must find order via client_order_id (0297)
        fresh_adapter = _make_adapter()
        found = fresh_adapter.find_order_by_client_order_id(client_id)
        assert found is not None, "fresh adapter could not find order by client_order_id"
        assert found.symbol == "AAPL"

        cancel_ack = adapter.cancel_order(ack.broker_order_id)
        assert cancel_ack.accepted

        time.sleep(1)

        final = adapter.get_order(ack.broker_order_id)
        assert final is not None
        assert final.state == "CANCELLED"

    def test_poll_order_events_detects_cancelled_order(self):
        """poll_order_events() emits CANCELLED event after cancel is confirmed (0299)."""
        from trade_engine.models import TradeIntent, Side, InstrumentType, OrderType, TimeInForce
        adapter = _make_adapter(submission_enabled=True)
        account_id = adapter.get_account_id()

        quote = adapter.get_quote("AAPL")
        assert quote is not None
        far_below = round(quote.bid * 0.90, 2)

        client_id = f"test-poll-{uuid.uuid4().hex[:8]}"
        intent = TradeIntent(
            intent_id="integration-test-poll",
            account_id=account_id,
            recommendation_id=None, agent_run_id=None,
            instrument_type=InstrumentType.EQUITY,
            symbol="AAPL", side=Side.BUY, quantity=1.0,
            contracts=None, option_type=None, strike=None, expiration=None,
            order_type=OrderType.LIMIT, limit_price=far_below,
            time_in_force=TimeInForce.DAY,
            strategy="integration-test", thesis_version=None,
            strategy_config_hash=None, policy_hash=None,
            valid_until="2099-12-31T23:59:59Z", created_at="2026-09-14T00:00:00Z",
        )

        ack = adapter.submit_order(intent, client_order_id=client_id)
        assert ack.broker_order_id

        time.sleep(1)

        # Cancel then poll — must emit CANCELLED event
        adapter.cancel_order(ack.broker_order_id)
        time.sleep(2)

        events = adapter.poll_order_events(account_id)
        event_types = {e.event_type for e in events}
        assert "CANCELLED" in event_types, f"expected CANCELLED in {event_types}"

    def test_initialize_trading_session_with_open_order_reaches_trading_ready(self):
        """initialize_trading_session() with one WORKING order in broker open set → TRADING_READY."""
        from trade_engine import execution_engine
        from trade_engine.models import TradeIntent, Side, InstrumentType, OrderType, TimeInForce
        adapter = _make_adapter(submission_enabled=True)
        account_id = adapter.get_account_id()

        quote = adapter.get_quote("AAPL")
        assert quote is not None
        far_below = round(quote.bid * 0.90, 2)

        client_id = f"test-init-{uuid.uuid4().hex[:8]}"
        intent_id = f"intent-{uuid.uuid4().hex[:8]}"
        intent = TradeIntent(
            intent_id=intent_id, account_id=account_id,
            recommendation_id=None, agent_run_id=None,
            instrument_type=InstrumentType.EQUITY,
            symbol="AAPL", side=Side.BUY, quantity=1.0,
            contracts=None, option_type=None, strike=None, expiration=None,
            order_type=OrderType.LIMIT, limit_price=far_below,
            time_in_force=TimeInForce.DAY,
            strategy="integration-test", thesis_version=None,
            strategy_config_hash=None, policy_hash=None,
            valid_until="2099-12-31T23:59:59Z", created_at="2026-09-14T00:00:00Z",
        )
        ack = adapter.submit_order(intent, client_order_id=client_id)

        # Seed local DB to reflect the submitted order
        conn = _make_integration_conn(account_id)
        now = "2026-09-14T09:00:00Z"
        conn.execute(
            "INSERT OR IGNORE INTO trade_intents "
            "(intent_id, account_id, symbol, side, quantity, limit_price, status, created_at, valid_until, instrument_type, order_type, time_in_force, strategy, thesis_version, strategy_config_hash, policy_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (intent_id, account_id, "AAPL", "BUY", 1.0, far_below, "PENDING", now, "2099-12-31T23:59:59Z",
             "EQUITY", "LIMIT", "DAY", "integration-test", None, None, None),
        )
        conn.execute(
            "INSERT OR IGNORE INTO orders "
            "(order_id, intent_id, account_id, symbol, side, quantity, order_type, state, "
            "broker_order_id, client_order_id, submitted_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ack.broker_order_id, intent_id, account_id, "AAPL", "BUY", 1.0, "LIMIT", "WORKING",
             ack.broker_order_id, client_id, now, now),
        )
        conn.commit()

        try:
            policy = _permissive_policy(account_id)
            with patch("trade_engine.execution_engine.load_policy", return_value=policy):
                state = execution_engine.initialize_trading_session(account_id, conn, broker=adapter)
            assert state == execution_engine.TradingReadyState.TRADING_READY
        finally:
            adapter.cancel_order(ack.broker_order_id)


# ── Phase 3b: Marketable fill + DB assertions + restart replay ────────────────

@integration
@skip_no_creds
class TestMarketableFill:
    """Submit a 1-share marketable LIMIT order, assert full DB settlement, replay is idempotent.

    Requires ALPACA_INTEGRATION_SUBMIT=1, ALPACA_EXPECTED_ACCOUNT_ID, AND
    ALPACA_INTEGRATION_FILL=1. Only run during market hours — order may not fill otherwise.
    """

    @pytest.fixture(autouse=True)
    def require_fill_flag(self):
        if os.environ.get("ALPACA_INTEGRATION_SUBMIT") != "1":
            pytest.skip("ALPACA_INTEGRATION_SUBMIT != '1'")
        if not os.environ.get("ALPACA_EXPECTED_ACCOUNT_ID"):
            pytest.skip("ALPACA_EXPECTED_ACCOUNT_ID not set")
        if os.environ.get("ALPACA_INTEGRATION_FILL") != "1":
            pytest.skip("ALPACA_INTEGRATION_FILL != '1' — skipping marketable fill test")

    def test_marketable_fill_settles_db_and_replay_is_idempotent(self):
        """Phase 3 + matrix points 2, 4, 5: buy 1 share, assert DB state, replay fills, check idempotency."""
        from trade_engine.execution_engine import apply_broker_fill, initialize_trading_session, TradingReadyState

        adapter = _make_adapter(submission_enabled=True)
        account_id = adapter.get_account_id()

        # Use a low-price liquid ETF to minimise paper capital impact
        symbol = "SOXS"
        quote = adapter.get_quote(symbol)
        assert quote is not None and quote.ask > 0, f"market may be closed — {symbol} ask is 0"

        # Submit at ask + 2% to maximise fill probability
        limit_price = round(quote.ask * 1.02, 2)
        client_id = f"fill-test-{uuid.uuid4().hex[:8]}"
        intent_id = f"intent-fill-{uuid.uuid4().hex[:8]}"
        order_id = f"local-{uuid.uuid4().hex[:8]}"

        from trade_engine.models import TradeIntent, Side, InstrumentType, OrderType, TimeInForce
        intent = TradeIntent(
            intent_id=intent_id, account_id=account_id,
            recommendation_id=None, agent_run_id=None,
            instrument_type=InstrumentType.EQUITY,
            symbol=symbol, side=Side.BUY, quantity=1.0,
            contracts=None, option_type=None, strike=None, expiration=None,
            order_type=OrderType.LIMIT, limit_price=limit_price,
            time_in_force=TimeInForce.DAY,
            strategy="integration-test", thesis_version=None,
            strategy_config_hash=None, policy_hash=None,
            valid_until="2099-12-31T23:59:59Z", created_at="2026-09-14T00:00:00Z",
        )

        # Seed DB with the real broker cash so reconciliation doesn't mismatch
        broker_acct = adapter.get_broker_account(account_id)
        starting_cash = broker_acct.cash
        conn = _make_integration_conn(account_id, cash=starting_cash)
        now = "2026-09-14T09:00:00Z"
        conn.execute(
            "INSERT OR IGNORE INTO trade_intents "
            "(intent_id, account_id, symbol, side, quantity, limit_price, status, created_at, valid_until, instrument_type, order_type, time_in_force, strategy, thesis_version, strategy_config_hash, policy_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (intent_id, account_id, symbol, "BUY", 1.0, limit_price, "PENDING", now, "2099-12-31T23:59:59Z",
             "EQUITY", "LIMIT", "DAY", "integration-test", None, None, None),
        )

        ack = adapter.submit_order(intent, client_order_id=client_id)
        broker_order_id = ack.broker_order_id

        conn.execute(
            "INSERT OR IGNORE INTO orders "
            "(order_id, intent_id, account_id, symbol, side, quantity, order_type, state, "
            "broker_order_id, client_order_id, submitted_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, intent_id, account_id, symbol, "BUY", 1.0, "LIMIT", "WORKING",
             broker_order_id, client_id, now, now),
        )
        conn.commit()

        # Poll up to 60 s for fill
        filled_order = None
        for _ in range(12):
            time.sleep(5)
            o = adapter.get_order(broker_order_id)
            if o and o.state == "FILLED":
                filled_order = o
                break
        if filled_order is None:
            adapter.cancel_order(broker_order_id)
            pytest.skip(f"Order {broker_order_id} did not fill within 60 s — market may be closed")

        # Fetch authoritative fills and apply
        fills = adapter.get_fills_for_order(broker_order_id)
        assert len(fills) > 0, "FILLED order returned no fills from activities endpoint"
        assert all(f.broker_fill_id for f in fills), "fill is missing broker_fill_id"

        fill_ids_before = set()
        for bf in fills:
            apply_broker_fill(bf, account_id, conn)
            fill_ids_before.add(bf.broker_fill_id)

        # Assert: fills table has rows matching the applied fills
        fill_rows = conn.execute("SELECT fill_id FROM fills WHERE account_id=?", (account_id,)).fetchall()
        assert {r["fill_id"] for r in fill_rows} == fill_ids_before, "fills table missing expected fill IDs"

        # Assert: position updated
        pos_row = conn.execute(
            "SELECT qty FROM position_snapshots WHERE account_id=? AND symbol=?", (account_id, symbol)
        ).fetchone()
        assert pos_row is not None, "position_snapshots not updated after fill"
        assert pos_row["qty"] >= 1.0, f"expected >= 1 share, got {pos_row['qty']}"

        # Assert: cash debited
        acct_row = conn.execute("SELECT current_cash FROM trading_accounts WHERE account_id=?", (account_id,)).fetchone()
        assert acct_row["current_cash"] < starting_cash, "cash not debited after fill"

        # Assert: executed_actions row present (matrix point 5)
        ea_rows = conn.execute("SELECT fill_id FROM executed_actions WHERE fill_id IS NOT NULL").fetchall()
        ea_fill_ids = {r["fill_id"] for r in ea_rows}
        assert fill_ids_before.issubset(ea_fill_ids), "executed_actions missing rows for fill IDs"

        # Matrix point 4: replay fills → idempotent (row counts unchanged)
        fill_count_before = conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
        ea_count_before = conn.execute("SELECT COUNT(*) FROM executed_actions").fetchone()[0]
        for bf in fills:
            apply_broker_fill(bf, account_id, conn)
        fill_count_after = conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
        ea_count_after = conn.execute("SELECT COUNT(*) FROM executed_actions").fetchone()[0]
        assert fill_count_after == fill_count_before, "replay changed fills row count"
        assert ea_count_after == ea_count_before, "replay changed executed_actions row count"

        # Matrix point 2: restart — initialize_trading_session() imports fills, reaches TRADING_READY
        conn2 = _make_integration_conn(account_id, cash=starting_cash)
        conn2.execute(
            "INSERT OR IGNORE INTO trade_intents "
            "(intent_id, account_id, symbol, side, quantity, limit_price, status, created_at, valid_until, instrument_type, order_type, time_in_force, strategy, thesis_version, strategy_config_hash, policy_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (intent_id, account_id, symbol, "BUY", 1.0, limit_price, "PENDING", now, "2099-12-31T23:59:59Z",
             "EQUITY", "LIMIT", "DAY", "integration-test", None, None, None),
        )
        conn2.execute(
            "INSERT OR IGNORE INTO orders "
            "(order_id, intent_id, account_id, symbol, side, quantity, order_type, state, "
            "broker_order_id, client_order_id, submitted_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, intent_id, account_id, symbol, "BUY", 1.0, "LIMIT", "WORKING",
             broker_order_id, client_id, now, now),
        )
        conn2.commit()

        fresh_adapter = _make_adapter()
        policy = _permissive_policy(account_id)
        with patch("trade_engine.execution_engine.load_policy", return_value=policy):
            restart_state = initialize_trading_session(account_id, conn2, broker=fresh_adapter)
        assert restart_state == TradingReadyState.TRADING_READY, \
            f"restart did not reach TRADING_READY: {restart_state}"

        # After restart, fills must be present in conn2 (imported by initialize_trading_session)
        restart_fills = conn2.execute("SELECT fill_id FROM fills WHERE account_id=?", (account_id,)).fetchall()
        assert len(restart_fills) > 0, "initialize_trading_session() did not import fills on restart"


# ── Market clock integration (0326) ──────────────────────────────────────────

@integration
@skip_no_creds
def test_get_market_clock_real_endpoint():
    """GET /v2/clock returns is_open, next_open, next_close on the real paper API (0326)."""
    adapter = _make_adapter()
    clock = adapter.get_market_clock()
    assert "is_open" in clock, f"is_open missing from clock response: {clock}"
    assert "next_open" in clock, f"next_open missing from clock response: {clock}"
    assert "next_close" in clock, f"next_close missing from clock response: {clock}"
    assert isinstance(clock["is_open"], bool), f"is_open should be bool, got: {type(clock['is_open'])}"
