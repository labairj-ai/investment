"""Tests for the trade engine: models, risk engine, shadow broker, intent builder (0190-0197)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from trade_engine.models import (
    AccountMode,
    ExecutionResult,
    Fill,
    InstrumentType,
    IntentStatus,
    InvalidStateTransition,
    Order,
    OrderState,
    OrderType,
    RiskDecision,
    RuleCheck,
    RuleResult,
    Side,
    TimeInForce,
    TradingAccount,
    TradeIntent,
)
from trade_engine.policy import TradingPolicy, load_policy
from trade_engine import risk_engine
from trade_engine.shadow_broker import Quote, ShadowBroker
from trade_engine import intent_builder
from trade_engine import execution_engine
from trade_engine import market_calendar


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_conn() -> sqlite3.Connection:
    """In-memory SQLite DB with trade engine schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # Bootstrap tables needed by trade engine tests
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trading_accounts (
            account_id TEXT PRIMARY KEY, name TEXT, mode TEXT,
            starting_capital REAL, current_cash REAL, broker TEXT,
            trading_enabled INTEGER DEFAULT 1, policy_version TEXT, created_at TEXT,
            nav_high_water REAL
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
            account_cash_at_eval REAL, account_nav_at_eval REAL
        );
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, intent_id TEXT, account_id TEXT,
            symbol TEXT, side TEXT, quantity REAL, contracts INTEGER,
            order_type TEXT, limit_price REAL, state TEXT DEFAULT 'PENDING',
            time_in_force TEXT DEFAULT 'DAY',
            broker_order_id TEXT, submitted_at TEXT, updated_at TEXT,
            fill_qty REAL DEFAULT 0, fill_cash REAL DEFAULT 0,
            market_data_status TEXT
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
            cash REAL, nav REAL, buying_power REAL, snapshot_at TEXT
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
            expiration TEXT, iv REAL, bid REAL, ask REAL, spread_pct REAL,
            captured_at REAL
        );
        CREATE TABLE IF NOT EXISTS event_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT,
            event_type TEXT, event_date TEXT
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
        CREATE TABLE IF NOT EXISTS investment_theses (
            id INTEGER PRIMARY KEY, ticker TEXT
        );
    """)
    # Seed account
    conn.execute(
        """INSERT INTO trading_accounts
           (account_id, name, mode, starting_capital, current_cash,
            trading_enabled, policy_version, created_at)
           VALUES ('AGENTIC_SHADOW_01','Test Shadow','shadow',10000,10000,1,'1.0','2026-01-01T00:00:00+00:00')"""
    )
    conn.commit()
    return conn


def _make_policy(overrides: dict | None = None) -> TradingPolicy:
    base = {
        "policy_version": "1.0",
        "account_id": "AGENTIC_SHADOW_01",
        "capital": {"starting_capital": 10000, "minimum_cash_pct": 10, "minimum_cash_abs": 500},
        "equities": {"buy_allowed": True, "sell_allowed": True, "shorting_allowed": False,
                     "max_single_position_pct": 10, "max_new_position_pct": 5},
        "options": {"covered_calls_allowed": True, "naked_options_allowed": False,
                    "max_contracts_per_symbol": 1},
        "execution": {"market_orders_allowed": False, "max_orders_per_day": 5,
                      "max_daily_notional_pct": 20, "max_slippage_pct": 1.0, "min_limit_price": 0.01},
        "risk": {"max_drawdown_pct": 10, "max_daily_loss_pct": 3, "max_weekly_loss_pct": 7},
        "circuit_breakers": {"trading_enabled": True, "halt_on_position_mismatch": True,
                              "halt_on_data_stale_minutes": 60, "halt_on_daily_loss_pct": 3},
    }
    if overrides:
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = {**base[k], **v}
            else:
                base[k] = v
    raw = json.dumps(base)
    return TradingPolicy(
        policy_version=base["policy_version"],
        account_id=base["account_id"],
        capital=base["capital"],
        equities=base["equities"],
        options=base["options"],
        execution=base["execution"],
        risk=base["risk"],
        circuit_breakers=base["circuit_breakers"],
        _raw_json=raw,
    )


def _make_account(cash: float = 10000.0) -> TradingAccount:
    return TradingAccount(
        account_id="AGENTIC_SHADOW_01",
        name="Test",
        mode=AccountMode.SHADOW,
        starting_capital=10000.0,
        current_cash=cash,
        trading_enabled=True,
        policy_version="1.0",
    )


def _future_iso(minutes: int = 60) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _past_iso(minutes: int = 60) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _make_intent(**kwargs) -> TradeIntent:
    defaults = dict(
        intent_id=str(uuid.uuid4()),
        account_id="AGENTIC_SHADOW_01",
        recommendation_id=None,
        agent_run_id=None,
        instrument_type=InstrumentType.EQUITY,
        symbol="ANET",
        side=Side.BUY,
        quantity=10.0,
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
        valid_until=_future_iso(),
        created_at=datetime.now(timezone.utc).isoformat(),
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


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Models
# ═══════════════════════════════════════════════════════════════════════════════

class TestTradeIntentModel:
    def test_is_expired_past(self):
        i = _make_intent(valid_until=_past_iso())
        assert i.is_expired()

    def test_is_expired_future(self):
        i = _make_intent(valid_until=_future_iso())
        assert not i.is_expired()

    def test_to_db_dict_round_trip_keys(self):
        i = _make_intent()
        d = i.to_db_dict()
        assert "intent_id" in d
        assert "limit_price" in d
        assert "status" in d
        assert d["status"] == "PENDING"
        assert d["side"] == "BUY"

    def test_from_db_row_round_trip(self):
        conn = _make_conn()
        i = _make_intent()
        _insert_intent(conn, i)
        row = conn.execute("SELECT * FROM trade_intents WHERE intent_id=?", (i.intent_id,)).fetchone()
        i2 = TradeIntent.from_db_row(row)
        assert i2.intent_id == i.intent_id
        assert i2.symbol == i.symbol
        assert i2.side == Side.BUY

    def test_notional(self):
        i = _make_intent(quantity=10.0, limit_price=142.44)
        assert abs(i.notional() - 1424.4) < 0.01


class TestOrderModel:
    def test_valid_transitions(self):
        o = Order(
            order_id="1", intent_id="i", account_id="A", symbol="X",
            side=Side.BUY, quantity=10.0, contracts=None,
            order_type=OrderType.LIMIT, limit_price=100.0,
        )
        o.transition(OrderState.SUBMITTED)
        assert o.state == OrderState.SUBMITTED
        o.transition(OrderState.WORKING)
        assert o.state == OrderState.WORKING
        o.transition(OrderState.FILLED)
        assert o.state == OrderState.FILLED

    def test_invalid_transition_raises(self):
        o = Order(
            order_id="1", intent_id="i", account_id="A", symbol="X",
            side=Side.BUY, quantity=10.0, contracts=None,
            order_type=OrderType.LIMIT, limit_price=100.0,
            state=OrderState.FILLED,
        )
        with pytest.raises(InvalidStateTransition):
            o.transition(OrderState.WORKING)

    def test_pending_to_filled_invalid(self):
        o = Order(
            order_id="1", intent_id="i", account_id="A", symbol="X",
            side=Side.BUY, quantity=10.0, contracts=None,
            order_type=OrderType.LIMIT, limit_price=100.0,
        )
        with pytest.raises(InvalidStateTransition):
            o.transition(OrderState.FILLED)


class TestFillModel:
    def test_cash_impact_buy(self):
        f = Fill("f1", "o1", "A", "X", Side.BUY, qty=10, price=100, fee=0,
                 fill_source="shadow", filled_at="2026-01-01T00:00:00+00:00")
        assert f.cash_impact() == -1000.0

    def test_cash_impact_sell(self):
        f = Fill("f1", "o1", "A", "X", Side.SELL, qty=10, price=100, fee=1,
                 fill_source="shadow", filled_at="2026-01-01T00:00:00+00:00")
        assert f.cash_impact() == 999.0

    def test_to_dict_round_trip(self):
        f = Fill("f1", "o1", "A", "X", Side.BUY, qty=5, price=50, fee=0,
                 fill_source="shadow", filled_at="2026-01-01T00:00:00+00:00")
        d = f.to_dict()
        assert d["side"] == "BUY"
        assert d["qty"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TradingPolicy
# ═══════════════════════════════════════════════════════════════════════════════

class TestTradingPolicy:
    def test_load_policy_valid(self):
        p = _make_policy()
        assert p.policy_version == "1.0"
        assert p.trading_enabled() is True
        assert p.buy_allowed() is True
        assert p.market_orders_allowed() is False
        assert p.max_single_position_pct() == 10.0
        assert p.min_cash_pct() == 10.0
        assert p.max_orders_per_day() == 5

    def test_trading_enabled_false(self):
        p = _make_policy({"circuit_breakers": {"trading_enabled": False}})
        assert p.trading_enabled() is False

    def test_policy_hash_consistent(self):
        p = _make_policy()
        h1 = p.policy_hash()
        h2 = p.policy_hash()
        assert h1 == h2
        assert len(h1) == 12

    def test_load_policy_wrong_account_raises(self, tmp_path):
        policy_json = tmp_path / "trading_policy.json"
        policy_json.write_text(json.dumps({
            "policy_version": "1.0",
            "account_id": "OTHER_ACCOUNT",
            "capital": {}, "equities": {}, "options": {},
            "execution": {}, "risk": {}, "circuit_breakers": {},
        }))
        from trade_engine.policy import load_policy as _lp
        with pytest.raises(ValueError, match="does not match"):
            _lp("AGENTIC_SHADOW_01", policy_path=policy_json)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Risk Engine — one test per rule
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskEngine:
    # ── 1. TRADING_ENABLED ────────────────────────────────────────────────────
    def test_trading_disabled_rejects(self):
        conn = _make_conn()
        intent = _make_intent()
        _insert_intent(conn, intent)
        policy = _make_policy({"circuit_breakers": {"trading_enabled": False}})
        account = _make_account()
        dec = risk_engine.evaluate(intent, policy, account, conn)
        assert dec.decision == "REJECTED"
        check = next(c for c in dec.checks if c.rule == "TRADING_ENABLED")
        assert check.result == RuleResult.FAIL

    # ── 2. VALID_ACCOUNT ──────────────────────────────────────────────────────
    def test_unknown_account_rejects(self):
        conn = _make_conn()
        intent = _make_intent(account_id="UNKNOWN_ACCT")
        _insert_intent(conn, intent)
        # Account row doesn't exist
        policy = _make_policy()
        account = _make_account()
        account = TradingAccount(
            account_id="UNKNOWN_ACCT", name="?", mode=AccountMode.SHADOW,
            starting_capital=0, current_cash=0, trading_enabled=True, policy_version="1.0",
        )
        dec = risk_engine.evaluate(intent, policy, account, conn)
        assert dec.decision == "REJECTED"
        check = next(c for c in dec.checks if c.rule == "VALID_ACCOUNT")
        assert check.result == RuleResult.FAIL

    # ── 3. INTENT_NOT_EXPIRED ─────────────────────────────────────────────────
    def test_expired_intent_rejects(self):
        conn = _make_conn()
        intent = _make_intent(valid_until=_past_iso())
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn)
        assert dec.decision == "REJECTED"
        check = next(c for c in dec.checks if c.rule == "INTENT_NOT_EXPIRED")
        assert check.result == RuleResult.FAIL

    # ── 4. NO_DUPLICATE_INTENT ────────────────────────────────────────────────
    def test_duplicate_recommendation_rejects(self):
        conn = _make_conn()
        rec_id = 42
        # Insert first APPROVED intent
        existing = _make_intent(recommendation_id=rec_id)
        _insert_intent(conn, existing)
        conn.execute(
            "UPDATE trade_intents SET status='APPROVED' WHERE intent_id=?",
            (existing.intent_id,),
        )
        conn.commit()
        # Second intent for same rec
        intent2 = _make_intent(recommendation_id=rec_id)
        _insert_intent(conn, intent2)
        dec = risk_engine.evaluate(intent2, _make_policy(), _make_account(), conn)
        assert dec.decision == "REJECTED"
        check = next(c for c in dec.checks if c.rule == "NO_DUPLICATE_INTENT")
        assert check.result == RuleResult.FAIL

    # ── 5. INSTRUMENT_ALLOWED ─────────────────────────────────────────────────
    def test_buy_not_allowed_rejects(self):
        conn = _make_conn()
        intent = _make_intent(side=Side.BUY)
        _insert_intent(conn, intent)
        policy = _make_policy({"equities": {"buy_allowed": False, "sell_allowed": True,
                                             "max_single_position_pct": 10,
                                             "max_new_position_pct": 5}})
        dec = risk_engine.evaluate(intent, policy, _make_account(), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "INSTRUMENT_ALLOWED")
        assert check.result == RuleResult.FAIL

    # ── 6. NO_MARKET_ORDER ────────────────────────────────────────────────────
    def test_market_order_rejects(self):
        conn = _make_conn()
        intent = _make_intent(order_type=OrderType.MARKET)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn)
        assert dec.decision == "REJECTED"
        check = next(c for c in dec.checks if c.rule == "NO_MARKET_ORDER")
        assert check.result == RuleResult.FAIL

    # ── 7. SUFFICIENT_CASH ────────────────────────────────────────────────────
    def test_insufficient_cash_rejects(self):
        conn = _make_conn()
        # With $500 cash and 10 shares @ $100 = $1000 cost, min cash = 10% of $500 = $50
        # but $500 - $1000 = -$500 < $500 min_cash_abs → FAIL
        intent = _make_intent(quantity=10.0, limit_price=100.0)
        _insert_intent(conn, intent)
        account = _make_account(cash=500.0)
        conn.execute("UPDATE trading_accounts SET current_cash=500 WHERE account_id='AGENTIC_SHADOW_01'")
        conn.commit()
        dec = risk_engine.evaluate(intent, _make_policy(), account, conn)
        assert dec.decision == "REJECTED"
        check = next(c for c in dec.checks if c.rule == "SUFFICIENT_CASH")
        assert check.result == RuleResult.FAIL
        assert check.before is not None

    # ── 8. MAX_POSITION_WEIGHT ────────────────────────────────────────────────
    def test_position_weight_exceeded_rejects(self):
        conn = _make_conn()
        # 50 shares @ $200 = $10000, NAV = $10000 → 100% position weight (>10% limit)
        intent = _make_intent(quantity=50.0, limit_price=200.0)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_POSITION_WEIGHT")
        assert check.result == RuleResult.FAIL

    # ── 9. MAX_NEW_POSITION_WEIGHT ────────────────────────────────────────────
    def test_new_position_weight_exceeded_rejects(self):
        conn = _make_conn()
        # 10 shares @ $60 = $600, NAV = $10000 → 6% > 5% new position limit
        intent = _make_intent(quantity=10.0, limit_price=60.0)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_NEW_POSITION_WEIGHT")
        assert check.result == RuleResult.FAIL
        assert check.after > 5.0

    # ── 10. MAX_DAILY_NOTIONAL ────────────────────────────────────────────────
    def test_daily_notional_exceeded_rejects(self):
        conn = _make_conn()
        # Add a fill of $1900 today to exhaust $2000 (20% of $10k) limit
        today = datetime.now(timezone.utc).isoformat()
        order_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO orders (order_id, intent_id, account_id, symbol, side, quantity, contracts, order_type, limit_price, state, time_in_force, submitted_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, "x", "AGENTIC_SHADOW_01", "X", "BUY", 19, None, "LIMIT", 100.0, "FILLED", "DAY", today, today)
        )
        conn.execute(
            "INSERT INTO fills (fill_id, order_id, account_id, symbol, side, qty, price, fee, fill_source, filled_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), order_id, "AGENTIC_SHADOW_01", "X", "BUY", 19, 100.0, 0, "shadow", today)
        )
        conn.commit()
        intent = _make_intent(quantity=2.0, limit_price=100.0)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_DAILY_NOTIONAL")
        assert check.result == RuleResult.FAIL

    # ── 11. MAX_ORDERS_PER_DAY ────────────────────────────────────────────────
    def test_max_orders_per_day_rejects(self):
        conn = _make_conn()
        today = datetime.now(timezone.utc).isoformat()
        for _ in range(5):
            conn.execute(
                "INSERT INTO orders (order_id, intent_id, account_id, symbol, side, quantity, contracts, order_type, limit_price, state, time_in_force, submitted_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), str(uuid.uuid4()), "AGENTIC_SHADOW_01", "X", "BUY", 1, None, "LIMIT", 100.0, "FILLED", "DAY", today, today)
            )
        conn.commit()
        intent = _make_intent()
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_ORDERS_PER_DAY")
        assert check.result == RuleResult.FAIL

    # ── 12. SELL_QUANTITY_COVERED ─────────────────────────────────────────────
    def test_sell_with_no_position_rejects(self):
        conn = _make_conn()
        intent = _make_intent(side=Side.SELL, quantity=10.0)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn)
        assert dec.decision == "REJECTED"
        check = next(c for c in dec.checks if c.rule == "SELL_QUANTITY_COVERED")
        assert check.result == RuleResult.FAIL

    # ── 13. NO_NAKED_OPTIONS ─────────────────────────────────────────────────
    def test_sell_to_open_without_underlying_rejects(self):
        conn = _make_conn()
        intent = _make_intent(
            side=Side.SELL_TO_OPEN,
            instrument_type=InstrumentType.OPTION,
            contracts=1,
            option_type="CALL",
            strike=150.0,
            expiration="2026-12-19",
        )
        _insert_intent(conn, intent)
        # No position → should fail NO_NAKED_OPTIONS
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "NO_NAKED_OPTIONS")
        assert check.result == RuleResult.FAIL

    # ── All checks pass → APPROVED ────────────────────────────────────────────
    def test_all_checks_pass_approves(self):
        conn = _make_conn()
        # Small BUY: 1 share @ $100 = $100 (1% of $10k NAV — well within limits)
        intent = _make_intent(quantity=1.0, limit_price=100.0)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn)
        assert dec.decision == "APPROVED"
        # Verify it was written to risk_decisions
        row = conn.execute(
            "SELECT * FROM risk_decisions WHERE intent_id=?", (intent.intent_id,)
        ).fetchone()
        assert row is not None
        checks_data = json.loads(row["checks_json"])
        assert len(checks_data) >= 10
        results = [c["result"] for c in checks_data]
        assert "FAIL" not in results


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ShadowBroker
# ═══════════════════════════════════════════════════════════════════════════════

class TestShadowBroker:
    def _make_order(self, conn, side=Side.BUY, qty=10.0, limit=100.0,
                    tif=TimeInForce.GTC) -> Order:
        """Default GTC so tests are not sensitive to current wall-clock time."""
        intent = _make_intent(side=side, quantity=qty, limit_price=limit,
                              time_in_force=tif)
        _insert_intent(conn, intent)
        broker = ShadowBroker(conn)
        return broker.submit_order(intent)

    def test_submit_creates_working_order(self):
        conn = _make_conn()
        order = self._make_order(conn)
        assert order.state == OrderState.WORKING

    def test_submit_idempotent_returns_same_order(self):
        conn = _make_conn()
        intent = _make_intent()
        _insert_intent(conn, intent)
        broker = ShadowBroker(conn)
        o1 = broker.submit_order(intent)
        o2 = broker.submit_order(intent)
        assert o1.order_id == o2.order_id

    def test_limit_buy_fills_when_ask_lte_limit(self):
        conn = _make_conn()
        order = self._make_order(conn, side=Side.BUY, qty=5.0, limit=100.0)
        broker = ShadowBroker(conn)
        quote = Quote(bid=98.0, ask=99.0, timestamp="t")  # ask 99 <= limit 100
        fill = broker.attempt_fill(order, quote)
        assert fill is not None
        assert fill.price == 99.0
        assert fill.qty == 5.0
        assert fill.side == Side.BUY

    def test_limit_buy_no_fill_when_ask_gt_limit(self):
        conn = _make_conn()
        order = self._make_order(conn, side=Side.BUY, qty=5.0, limit=100.0)
        broker = ShadowBroker(conn)
        quote = Quote(bid=101.0, ask=102.0, timestamp="t")  # ask 102 > limit 100
        fill = broker.attempt_fill(order, quote)
        assert fill is None

    def test_limit_sell_fills_when_bid_gte_limit(self):
        conn = _make_conn()
        # Add position first
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 10.0, 90.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        order = self._make_order(conn, side=Side.SELL, qty=5.0, limit=95.0)
        broker = ShadowBroker(conn)
        quote = Quote(bid=97.0, ask=98.0, timestamp="t")  # bid 97 >= limit 95
        fill = broker.attempt_fill(order, quote)
        assert fill is not None
        assert fill.price == 97.0

    def test_limit_sell_no_fill_when_bid_lt_limit(self):
        conn = _make_conn()
        order = self._make_order(conn, side=Side.SELL, qty=5.0, limit=95.0)
        broker = ShadowBroker(conn)
        quote = Quote(bid=93.0, ask=94.0, timestamp="t")  # bid 93 < limit 95
        fill = broker.attempt_fill(order, quote)
        assert fill is None

    def test_duplicate_fill_is_idempotent(self):
        conn = _make_conn()
        order = self._make_order(conn, side=Side.BUY, qty=5.0, limit=100.0)
        broker = ShadowBroker(conn)
        quote = Quote(bid=98.0, ask=99.0, timestamp="t")
        fill1 = broker.attempt_fill(order, quote)
        assert fill1 is not None
        # Manually call _apply_fill again with same fill_id → should be no-op
        broker._apply_fill(order, fill1)
        count = conn.execute("SELECT COUNT(*) FROM fills WHERE fill_id=?", (fill1.fill_id,)).fetchone()[0]
        assert count == 1

    def test_fill_updates_cash_correctly(self):
        conn = _make_conn()
        order = self._make_order(conn, side=Side.BUY, qty=5.0, limit=100.0)
        broker = ShadowBroker(conn)
        quote = Quote(bid=98.0, ask=99.0, timestamp="t")
        broker.attempt_fill(order, quote)
        cash = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]
        # 10000 - 5*99 = 10000 - 495 = 9505
        assert abs(cash - 9505.0) < 0.01

    def test_fill_updates_position(self):
        conn = _make_conn()
        order = self._make_order(conn, side=Side.BUY, qty=10.0, limit=100.0)
        broker = ShadowBroker(conn)
        quote = Quote(bid=98.0, ask=99.0, timestamp="t")
        broker.attempt_fill(order, quote)
        pos = conn.execute(
            "SELECT qty, avg_cost FROM position_snapshots WHERE account_id='AGENTIC_SHADOW_01' AND symbol='ANET'"
        ).fetchone()
        assert pos is not None
        assert abs(pos["qty"] - 10.0) < 0.01
        assert abs(pos["avg_cost"] - 99.0) < 0.01

    def test_invalid_state_transition_raises(self):
        conn = _make_conn()
        order = self._make_order(conn)
        with pytest.raises(InvalidStateTransition):
            order.transition(OrderState.PENDING)  # WORKING → PENDING not allowed

    def test_cancel_order(self):
        conn = _make_conn()
        intent = _make_intent()
        _insert_intent(conn, intent)
        broker = ShadowBroker(conn)
        order = broker.submit_order(intent)
        cancelled = broker.cancel_order(order.order_id)
        assert cancelled.state == OrderState.CANCELLED


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Cash + Position conservation invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestConservationInvariants:
    def test_cash_conservation_after_multiple_fills(self):
        """starting_capital + sells - buys - fees == current_cash after N fills."""
        conn = _make_conn()
        broker = ShadowBroker(conn)

        # Buy 10 shares @ 100
        i1 = _make_intent(quantity=10.0, limit_price=100.0, side=Side.BUY)
        _insert_intent(conn, i1)
        o1 = broker.submit_order(i1)
        broker.attempt_fill(o1, Quote(bid=99, ask=100, timestamp="t"))

        # Buy 5 more @ 110
        i2 = _make_intent(quantity=5.0, limit_price=110.0, side=Side.BUY, symbol="ANET")
        _insert_intent(conn, i2)
        o2 = broker.submit_order(i2)
        broker.attempt_fill(o2, Quote(bid=108, ask=110, timestamp="t"))

        # Sell 3 @ 120
        conn.execute(
            "UPDATE position_snapshots SET qty=15, avg_cost=103 WHERE account_id='AGENTIC_SHADOW_01' AND symbol='ANET'"
        )
        conn.commit()
        i3 = _make_intent(quantity=3.0, limit_price=119.0, side=Side.SELL, symbol="ANET")
        _insert_intent(conn, i3)
        o3 = broker.submit_order(i3)
        broker.attempt_fill(o3, Quote(bid=120, ask=121, timestamp="t"))

        result = broker.verify_conservation("AGENTIC_SHADOW_01")
        assert result["ok"], f"Conservation failed: {result}"

    def test_position_conservation_per_symbol(self):
        """sum(buy_fills qty) - sum(sell_fills qty) == current_position qty."""
        conn = _make_conn()
        broker = ShadowBroker(conn)

        i1 = _make_intent(quantity=20.0, limit_price=50.0, side=Side.BUY, symbol="NVDA")
        _insert_intent(conn, i1)
        o1 = broker.submit_order(i1)
        broker.attempt_fill(o1, Quote(bid=49, ask=50, timestamp="t"))

        # Set position qty manually to simulate existing state
        pos_row = conn.execute(
            "SELECT qty FROM position_snapshots WHERE account_id='AGENTIC_SHADOW_01' AND symbol='NVDA'"
        ).fetchone()
        assert pos_row is not None
        bought_qty = 20.0

        i2 = _make_intent(quantity=7.0, limit_price=55.0, side=Side.SELL, symbol="NVDA")
        _insert_intent(conn, i2)
        o2 = broker.submit_order(i2)
        broker.attempt_fill(o2, Quote(bid=56, ask=57, timestamp="t"))

        pos = conn.execute(
            "SELECT qty FROM position_snapshots WHERE account_id='AGENTIC_SHADOW_01' AND symbol='NVDA'"
        ).fetchone()
        assert abs(pos["qty"] - 13.0) < 0.01  # 20 - 7


# ═══════════════════════════════════════════════════════════════════════════════
# 6. IntentBuilder
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntentBuilder:
    def _insert_rec(self, conn, action="BUY", status="accepted", payload=None) -> int:
        if payload is None:
            payload = {"price": 100.0}
        cur = conn.execute(
            "INSERT INTO recommendations (ticker, action, action_payload_json, status, created_at) VALUES (?,?,?,?,?)",
            ("ANET", action, json.dumps(payload), status, 0),
        )
        conn.commit()
        return cur.lastrowid

    def test_buy_intent_quantity_sizing(self):
        conn = _make_conn()
        rec_id = self._insert_rec(conn, action="BUY", payload={"price": 100.0})
        policy = _make_policy()
        # max_new_position_pct=5%, NAV=$10k → target=$500
        # limit_price with 1% slippage = 101.0
        # qty = floor(500/101) = 4 (sized against slipped price so risk engine passes)
        result = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", policy, conn)
        assert result is not None
        assert result.side == Side.BUY
        assert result.quantity == 4.0
        assert result.instrument_type == InstrumentType.EQUITY
        assert result.limit_price == 101.0  # 100 * 1.01

    def test_trim_intent_uses_trim_fraction(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 20.0, 80.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        rec_id = self._insert_rec(conn, action="TRIM", payload={"price": 100.0, "trim_fraction": 0.25})
        result = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", _make_policy(), conn)
        assert result is not None
        assert result.side == Side.SELL
        assert result.quantity == 5.0  # floor(20 * 0.25)

    def test_exit_intent_full_position(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 15.0, 80.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        rec_id = self._insert_rec(conn, action="EXIT", payload={"price": 100.0})
        result = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", _make_policy(), conn)
        assert result is not None
        assert result.side == Side.SELL
        assert result.quantity == 15.0

    def test_exit_no_position_returns_none(self):
        conn = _make_conn()
        rec_id = self._insert_rec(conn, action="EXIT", payload={"price": 100.0})
        result = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", _make_policy(), conn)
        assert result is None

    def test_unsupported_action_returns_none(self):
        conn = _make_conn()
        rec_id = self._insert_rec(conn, action="SELL_CC", payload={"price": 2.50})
        result = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", _make_policy(), conn)
        assert result is None

    def test_non_accepted_status_returns_none(self):
        conn = _make_conn()
        rec_id = self._insert_rec(conn, action="BUY", status="open", payload={"price": 100.0})
        result = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", _make_policy(), conn)
        assert result is None

    def test_buy_price_too_high_returns_none(self):
        conn = _make_conn()
        # NAV=$10k, new_pos_pct=5% → $500 max. If price=$600, floor(500/600)=0 → None
        rec_id = self._insert_rec(conn, action="BUY", payload={"price": 600.0})
        result = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", _make_policy(), conn)
        assert result is None

    def test_duplicate_build_returns_existing(self):
        conn = _make_conn()
        rec_id = self._insert_rec(conn, action="BUY", payload={"price": 100.0})
        policy = _make_policy()
        r1 = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", policy, conn)
        r2 = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", policy, conn)
        assert r1 is not None
        assert r2 is not None
        assert r1.intent_id == r2.intent_id  # idempotent

    def test_intent_written_to_db(self):
        conn = _make_conn()
        rec_id = self._insert_rec(conn, action="BUY", payload={"price": 100.0})
        result = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", _make_policy(), conn)
        assert result is not None
        row = conn.execute(
            "SELECT * FROM trade_intents WHERE intent_id=?", (result.intent_id,)
        ).fetchone()
        assert row is not None
        assert row["recommendation_id"] == rec_id
        assert row["status"] == "PENDING"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ExecutionEngine idempotency and end-to-end
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutionEngine:
    def _setup_accepted_rec(self, conn) -> int:
        cur = conn.execute(
            "INSERT INTO recommendations (ticker, action, action_payload_json, status, created_at) VALUES (?,?,?,?,?)",
            ("ANET", "BUY", json.dumps({"price": 100.0}), "accepted", 0),
        )
        conn.commit()
        return cur.lastrowid

    def test_rejected_intent_no_order_created(self):
        conn = _make_conn()
        # MARKET order will be rejected by NO_MARKET_ORDER rule
        intent = _make_intent(quantity=1.0, limit_price=100.0, order_type=OrderType.MARKET)
        _insert_intent(conn, intent)

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()):
            result = execution_engine.process_intent(intent.intent_id, conn)

        assert result.decision == "REJECTED"
        assert result.order_id is None
        assert result.fill is None
        # Intent status updated
        status = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent.intent_id,)
        ).fetchone()["status"]
        assert status == "REJECTED"

    def test_approved_intent_creates_fill(self):
        conn = _make_conn()
        intent = _make_intent(quantity=1.0, limit_price=100.0)
        _insert_intent(conn, intent)

        mock_quote = Quote(bid=99.0, ask=100.0, timestamp="t")
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_get_quote", return_value=mock_quote):
            result = execution_engine.process_intent(intent.intent_id, conn)

        assert result.decision == "APPROVED"
        assert result.fill is not None
        assert result.fill.qty == 1.0

    def test_fill_written_to_executed_actions(self):
        conn = _make_conn()
        rec_id = self._setup_accepted_rec(conn)
        intent = _make_intent(quantity=1.0, limit_price=100.0, recommendation_id=rec_id)
        _insert_intent(conn, intent)

        mock_quote = Quote(bid=99.0, ask=100.0, timestamp="t")
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_get_quote", return_value=mock_quote):
            result = execution_engine.process_intent(intent.intent_id, conn)

        assert result.fill is not None
        ea = conn.execute(
            "SELECT * FROM executed_actions WHERE fill_id=?", (result.fill.fill_id,)
        ).fetchone()
        assert ea is not None
        assert ea["recommendation_id"] == rec_id
        assert ea["source"] == "shadow"

    def test_crash_after_order_submit_no_double_order(self):
        """Restart after order created but before fill: same order_id returned."""
        conn = _make_conn()
        intent = _make_intent(quantity=1.0, limit_price=100.0)
        _insert_intent(conn, intent)

        # Simulate crash: manually create WORKING order for this intent
        order_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO orders (order_id, intent_id, account_id, symbol, side, quantity,
               contracts, order_type, limit_price, state, time_in_force, submitted_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, intent.intent_id, intent.account_id, intent.symbol,
             intent.side.value, intent.quantity, None, intent.order_type.value,
             intent.limit_price, "WORKING", "DAY", now, now),
        )
        conn.commit()

        mock_quote = Quote(bid=99.0, ask=100.0, timestamp="t")
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_get_quote", return_value=mock_quote):
            result = execution_engine.process_intent(intent.intent_id, conn)

        assert result.order_id == order_id  # same order, no duplicate
        # Only one order row
        count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE intent_id=?", (intent.intent_id,)
        ).fetchone()[0]
        assert count == 1

    def test_crash_after_fill_executed_actions_idempotent(self):
        """Re-running after fill already exists: executed_actions not double-written."""
        conn = _make_conn()
        rec_id = self._setup_accepted_rec(conn)
        intent = _make_intent(quantity=1.0, limit_price=100.0, recommendation_id=rec_id)
        _insert_intent(conn, intent)

        mock_quote = Quote(bid=99.0, ask=100.0, timestamp="t")
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_get_quote", return_value=mock_quote):
            execution_engine.process_intent(intent.intent_id, conn)
            # Mark intent PENDING again to simulate re-run
            conn.execute(
                "UPDATE trade_intents SET status='APPROVED' WHERE intent_id=?",
                (intent.intent_id,),
            )
            conn.commit()
            # Re-run — fill already exists
            execution_engine.process_intent(intent.intent_id, conn)

        # executed_actions should have exactly one row for this fill
        count = conn.execute(
            "SELECT COUNT(*) FROM executed_actions WHERE recommendation_id=?", (rec_id,)
        ).fetchone()[0]
        assert count == 1

    def test_end_to_end_buy_recommendation_to_executed_action(self):
        """Full flow: BUY recommendation → intent → risk → fill → executed_actions."""
        conn = _make_conn()
        rec_id = self._setup_accepted_rec(conn)
        policy = _make_policy()

        # Build intent from recommendation
        built_intent = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", policy, conn)
        assert built_intent is not None

        mock_quote = Quote(bid=99.0, ask=101.0, timestamp="t")  # ask == limit (101.0)
        with patch.object(execution_engine, "load_policy", return_value=policy), \
             patch.object(execution_engine, "_get_quote", return_value=mock_quote), \
             patch.object(market_calendar, "is_market_open", return_value=True):
            result = execution_engine.process_intent(built_intent.intent_id, conn)

        assert result.decision == "APPROVED"
        assert result.fill is not None

        ea = conn.execute(
            "SELECT * FROM executed_actions WHERE recommendation_id=?", (rec_id,)
        ).fetchone()
        assert ea is not None
        assert ea["ticker"] == "ANET"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. DB schema verification (0190)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDBSchema:
    def test_all_trade_engine_tables_exist(self):
        conn = _make_conn()
        expected_tables = [
            "trading_accounts", "trade_intents", "risk_decisions",
            "orders", "fills", "account_snapshots", "position_snapshots",
        ]
        existing = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for t in expected_tables:
            assert t in existing, f"Missing table: {t}"

    def test_agentic_shadow_01_seed(self):
        conn = _make_conn()
        row = conn.execute(
            "SELECT * FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()
        assert row is not None
        assert row["starting_capital"] == 10000.0
        assert row["current_cash"] == 10000.0
        assert row["mode"] == "shadow"
        assert row["trading_enabled"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Risk engine rules 14-18 (0208)
# ═══════════════════════════════════════════════════════════════════════════════

def _make_option_intent(**kwargs) -> TradeIntent:
    defaults = dict(
        intent_id=str(uuid.uuid4()),
        account_id="AGENTIC_SHADOW_01",
        recommendation_id=None,
        agent_run_id=None,
        instrument_type=InstrumentType.OPTION,
        symbol="ANET",
        side=Side.SELL_TO_OPEN,
        quantity=None,
        contracts=1,
        option_type="CALL",
        strike=160.0,
        expiration="2027-01-21",
        order_type=OrderType.LIMIT,
        limit_price=3.20,
        time_in_force=TimeInForce.GTC,
        strategy="test_cc",
        thesis_version=None,
        strategy_config_hash=None,
        policy_hash=None,
        valid_until=_future_iso(),
        created_at=datetime.now(timezone.utc).isoformat(),
        status=IntentStatus.PENDING,
    )
    defaults.update(kwargs)
    return TradeIntent(**defaults)


class TestRiskEngineRules14to18:
    """Dedicated tests for rules 14-18 (were untested in initial suite). 0208."""

    def _seed_underlying(self, conn, qty=100.0):
        conn.execute(
            "INSERT OR IGNORE INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", qty, 140.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()

    # ── 14. MAX_CONTRACTS_PER_SYMBOL ─────────────────────────────────────────

    def test_max_contracts_per_symbol_at_limit_rejects(self):
        """open=1 contract, limit=1, requesting 1 more → 1+1>1 → FAIL."""
        conn = _make_conn()
        self._seed_underlying(conn)
        # Simulate 1 open contract via a SELL_TO_OPEN fill
        conn.execute(
            """INSERT INTO orders (order_id, intent_id, account_id, symbol, side, quantity, contracts,
               order_type, limit_price, state, time_in_force, submitted_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), str(uuid.uuid4()), "AGENTIC_SHADOW_01", "ANET",
             "SELL_TO_OPEN", None, 1, "LIMIT", 3.20, "FILLED", "GTC",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        order_id = conn.execute("SELECT order_id FROM orders ORDER BY rowid DESC LIMIT 1").fetchone()["order_id"]
        conn.execute(
            "INSERT INTO fills (fill_id, order_id, account_id, symbol, side, qty, price, fee, fill_source, filled_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), order_id, "AGENTIC_SHADOW_01", "ANET", "SELL_TO_OPEN", 1, 3.20, 0, "shadow", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        intent = _make_option_intent(contracts=1)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(cash=9800.0), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_CONTRACTS_PER_SYMBOL")
        assert check.result == RuleResult.FAIL

    def test_max_contracts_off_by_one_fixed(self):
        """open=0, requesting 2, limit=1 → 0+2>1 → FAIL (was passing before fix). 0205."""
        conn = _make_conn()
        self._seed_underlying(conn, qty=200.0)
        intent = _make_option_intent(contracts=2)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(cash=9800.0), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_CONTRACTS_PER_SYMBOL")
        assert check.result == RuleResult.FAIL
        assert check.after == 2.0

    # ── 15. DATA_FRESHNESS ────────────────────────────────────────────────────

    def test_data_freshness_stale_quote_rejects(self):
        """Option quote older than halt_on_data_stale_minutes → FAIL."""
        conn = _make_conn()
        self._seed_underlying(conn)
        import time as _time
        stale_ts = _time.time() - (61 * 60)  # 61 minutes ago
        conn.execute(
            "INSERT INTO option_quote_snapshots (ticker, strike, expiration, iv, bid, ask, spread_pct, captured_at) VALUES (?,?,?,?,?,?,?,?)",
            ("ANET", 160.0, "2027-01-21", 0.30, 3.10, 3.30, 0.06, stale_ts),
        )
        conn.commit()
        intent = _make_option_intent()
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(cash=9800.0), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "DATA_FRESHNESS")
        assert check.result == RuleResult.FAIL

    # ── 16. NO_EARNINGS_CONFLICT ──────────────────────────────────────────────

    def test_no_earnings_conflict_rejects(self):
        """Earnings event between today and expiry → FAIL."""
        conn = _make_conn()
        self._seed_underlying(conn)
        conn.execute(
            "INSERT INTO event_calendar (ticker, event_type, event_date) VALUES (?,?,?)",
            ("ANET", "earnings", "2026-10-15"),
        )
        conn.commit()
        intent = _make_option_intent(expiration="2026-11-21")
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(cash=9800.0), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "NO_EARNINGS_CONFLICT")
        assert check.result == RuleResult.FAIL

    # ── 17. MAX_DAILY_LOSS ────────────────────────────────────────────────────

    def test_max_daily_loss_rejects(self):
        """Insert sell fills with realized_pnl summing to > limit → FAIL. 0202."""
        conn = _make_conn()
        today = datetime.now(timezone.utc).isoformat()
        # Insert a loss fill directly: $320 loss > $300 limit (3% of $10k)
        conn.execute(
            """INSERT INTO fills (fill_id, order_id, account_id, symbol, side, qty, price,
               fee, fill_source, filled_at, cost_basis, realized_pnl, realized_pnl_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), str(uuid.uuid4()), "AGENTIC_SHADOW_01", "ANET",
             "SELL", 10, 68.0, 0, "shadow", today, 1000.0, -320.0, -32.0),
        )
        conn.commit()
        intent = _make_intent()
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_DAILY_LOSS")
        assert check.result == RuleResult.FAIL
        assert check.before >= 300.0

    # ── 18. MAX_DRAWDOWN ─────────────────────────────────────────────────────

    def test_max_drawdown_rejects(self):
        """nav_high_water=$10000, current nav=$8900 → 11% drawdown > 10% limit → FAIL. 0201."""
        conn = _make_conn()
        # Set nav_high_water high
        conn.execute(
            "UPDATE trading_accounts SET nav_high_water=10000, current_cash=8900 WHERE account_id='AGENTIC_SHADOW_01'"
        )
        conn.commit()
        intent = _make_intent()
        _insert_intent(conn, intent)
        account = _make_account(cash=8900.0)
        dec = risk_engine.evaluate(intent, _make_policy(), account, conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_DRAWDOWN")
        assert check.result == RuleResult.FAIL
        assert check.before > 10.0


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Execution safety behaviors (0199-0208)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutionSafety:

    # ── 0200: fail-closed on missing quote ───────────────────────────────────

    def test_no_fill_when_quote_unavailable(self):
        """_get_quote returns None → order stays WORKING, no fill, market_data_status set."""
        conn = _make_conn()
        intent = _make_intent(quantity=1.0, limit_price=100.0)
        _insert_intent(conn, intent)
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_get_quote", return_value=None):
            result = execution_engine.process_intent(intent.intent_id, conn)
        assert result.decision == "APPROVED"
        assert result.fill is None
        order_row = conn.execute(
            "SELECT state, market_data_status FROM orders WHERE intent_id=?",
            (intent.intent_id,),
        ).fetchone()
        assert order_row["state"] == "WORKING"
        assert order_row["market_data_status"] == "unavailable"

    # ── 0203: market calendar — DAY orders expire outside session ────────────

    def test_day_order_expires_when_market_closed(self):
        """DAY order → attempt_fill when market is closed → EXPIRED, returns None."""
        conn = _make_conn()
        intent = _make_intent(quantity=1.0, limit_price=100.0, time_in_force=TimeInForce.DAY)
        _insert_intent(conn, intent)
        broker = ShadowBroker(conn)
        order = broker.submit_order(intent)
        assert order.state == OrderState.WORKING

        with patch.object(market_calendar, "is_market_open", return_value=False):
            fill = broker.attempt_fill(order, Quote(bid=99.0, ask=100.0, timestamp="t"))

        assert fill is None
        updated = broker.get_order(order.order_id)
        assert updated.state == OrderState.EXPIRED

    def test_gtc_order_fills_regardless_of_market_time(self):
        """GTC order → attempt_fill ignores market hours, fills on price."""
        conn = _make_conn()
        intent = _make_intent(quantity=1.0, limit_price=100.0, time_in_force=TimeInForce.GTC)
        _insert_intent(conn, intent)
        broker = ShadowBroker(conn)
        order = broker.submit_order(intent)

        with patch.object(market_calendar, "is_market_open", return_value=False):
            fill = broker.attempt_fill(order, Quote(bid=99.0, ask=100.0, timestamp="t"))

        assert fill is not None

    def test_market_calendar_blocks_saturday(self):
        """is_market_open() returns False on a Saturday."""
        from datetime import date as _date
        saturday = datetime(2026, 9, 12, 14, 0, 0, tzinfo=timezone.utc)  # 2026-09-12 is Saturday
        # Verify directly
        assert not market_calendar.is_trading_day(_date(2026, 9, 12))
        assert not market_calendar.is_market_open(saturday)

    def test_market_calendar_blocks_nyse_holiday(self):
        """is_market_open() returns False on NYSE holidays."""
        from datetime import date as _date
        xmas = datetime(2026, 12, 25, 12, 0, 0, tzinfo=timezone.utc)
        assert not market_calendar.is_trading_day(_date(2026, 12, 25))
        assert not market_calendar.is_market_open(xmas)

    def test_market_calendar_open_during_session(self):
        """is_market_open() returns True on a trading day at 2 PM ET."""
        try:
            import zoneinfo
            et = zoneinfo.ZoneInfo("America/New_York")
        except Exception:
            return  # skip if zoneinfo unavailable
        # 2026-09-14 is Monday
        trading_dt = datetime(2026, 9, 14, 14, 0, 0, tzinfo=et)
        assert market_calendar.is_trading_day(trading_dt.date())
        assert market_calendar.is_market_open(trading_dt)

    # ── 0199: WORKING order retried on next cycle ─────────────────────────────

    def test_working_order_retried_on_next_cycle(self):
        """Cycle 1: quote misses limit → WORKING. Cycle 2: quote crosses → FILLED."""
        conn = _make_conn()
        intent = _make_intent(quantity=1.0, limit_price=100.0, time_in_force=TimeInForce.GTC)
        _insert_intent(conn, intent)

        miss_quote = Quote(bid=98.0, ask=101.5, timestamp="t")  # ask 101.5 > limit 100 → no fill
        hit_quote = Quote(bid=99.0, ask=100.0, timestamp="t")   # ask 100.0 == limit 100 → fill

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_get_quote", return_value=miss_quote):
            result1 = execution_engine.process_intent(intent.intent_id, conn)

        assert result1.fill is None
        order_id = result1.order_id
        assert conn.execute("SELECT state FROM orders WHERE order_id=?", (order_id,)).fetchone()["state"] == "WORKING"

        # Cycle 2: retry open orders
        with patch.object(execution_engine, "_get_quote", return_value=hit_quote):
            fills = execution_engine.process_open_orders("AGENTIC_SHADOW_01", conn)

        assert len(fills) == 1
        assert conn.execute("SELECT state FROM orders WHERE order_id=?", (order_id,)).fetchone()["state"] == "FILLED"
        intent_status = conn.execute("SELECT status FROM trade_intents WHERE intent_id=?", (intent.intent_id,)).fetchone()["status"]
        assert intent_status == "FILLED"

    # ── 0202: realized P&L captured at fill time ─────────────────────────────

    def test_fill_captures_realized_pnl_on_sell(self):
        """Sell fill writes cost_basis and realized_pnl before position mutation. 0202."""
        conn = _make_conn()
        broker = ShadowBroker(conn)
        # Setup position: 10 shares @ $100
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 10.0, 100.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        sell_intent = _make_intent(side=Side.SELL, quantity=5.0, limit_price=119.0)
        _insert_intent(conn, sell_intent)
        order = broker.submit_order(sell_intent)
        fill = broker.attempt_fill(order, Quote(bid=120.0, ask=121.0, timestamp="t"))
        assert fill is not None

        fill_row = conn.execute("SELECT * FROM fills WHERE fill_id=?", (fill.fill_id,)).fetchone()
        assert fill_row["cost_basis"] == pytest.approx(500.0)    # 5 * $100
        assert fill_row["realized_pnl"] == pytest.approx(100.0)  # 5*120 - 500 = 100
        assert fill_row["realized_pnl_pct"] == pytest.approx(20.0)

    def test_fill_pnl_negative_on_loss(self):
        """Loss scenario: realized_pnl < 0."""
        conn = _make_conn()
        broker = ShadowBroker(conn)
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 10.0, 100.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        sell_intent = _make_intent(side=Side.SELL, quantity=10.0, limit_price=68.0)
        _insert_intent(conn, sell_intent)
        order = broker.submit_order(sell_intent)
        fill = broker.attempt_fill(order, Quote(bid=68.0, ask=69.0, timestamp="t"))
        assert fill is not None

        fill_row = conn.execute("SELECT * FROM fills WHERE fill_id=?", (fill.fill_id,)).fetchone()
        assert fill_row["realized_pnl"] == pytest.approx(-320.0)  # 10*68 - 10*100 = -320
        assert fill_row["realized_pnl_pct"] == pytest.approx(-32.0)

    def test_full_exit_at_loss_daily_loss_circuit_fires(self):
        """Buy 10@100, sell all 10@68, position deleted; MAX_DAILY_LOSS still fires. 0202."""
        conn = _make_conn()
        broker = ShadowBroker(conn)
        # Buy
        buy_intent = _make_intent(quantity=10.0, limit_price=100.0)
        _insert_intent(conn, buy_intent)
        buy_order = broker.submit_order(buy_intent)
        broker.attempt_fill(buy_order, Quote(bid=99.0, ask=100.0, timestamp="t"))

        # Sell all
        sell_intent = _make_intent(side=Side.SELL, quantity=10.0, limit_price=68.0)
        _insert_intent(conn, sell_intent)
        sell_order = broker.submit_order(sell_intent)
        broker.attempt_fill(sell_order, Quote(bid=68.0, ask=69.0, timestamp="t"))

        # Position should be deleted
        pos = conn.execute(
            "SELECT qty FROM position_snapshots WHERE account_id='AGENTIC_SHADOW_01' AND symbol='ANET'"
        ).fetchone()
        assert pos is None

        # Next BUY intent: MAX_DAILY_LOSS should FAIL (loss=$320 > $300 limit)
        next_intent = _make_intent(quantity=1.0, limit_price=50.0)
        _insert_intent(conn, next_intent)
        dec = risk_engine.evaluate(next_intent, _make_policy(), _make_account(), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_DAILY_LOSS")
        assert check.result == RuleResult.FAIL

    # ── 0201: concentration uses market value ─────────────────────────────────

    def test_concentration_uses_market_value(self):
        """After price doubles, market-value concentration fires before adding more. 0201."""
        conn = _make_conn()
        # Position: 10 shares, avg_cost=$100, market_value updated to $110 each
        conn.execute(
            """INSERT INTO position_snapshots
               (account_id, symbol, qty, avg_cost, instrument_type, as_of, market_price, market_value)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("AGENTIC_SHADOW_01", "ANET", 10.0, 100.0, "EQUITY", "2026-01-01", 110.0, 1100.0),
        )
        # Cash after buying 10@100 = $9000; NAV = $9000 + $1100 = $10100
        conn.execute("UPDATE trading_accounts SET current_cash=9000 WHERE account_id='AGENTIC_SHADOW_01'")
        conn.commit()

        # Try to add 5 more @ $110 → trade_cost=550; weight_after = (1100+550)/10100 = 16.3% > 10%
        intent = _make_intent(quantity=5.0, limit_price=110.0)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(cash=9000.0), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_POSITION_WEIGHT")
        assert check.result == RuleResult.FAIL

    # ── 0205: options multiplier ──────────────────────────────────────────────

    def test_options_cash_impact_multiplier(self):
        """SELL_TO_OPEN fill applies 100× multiplier: 1 contract @ $3.20 → $320. 0205."""
        fill = Fill(
            fill_id="x", order_id="o", account_id="a", symbol="ANET",
            side=Side.SELL_TO_OPEN, qty=1.0, price=3.20, fee=0.0,
            fill_source="shadow", filled_at="t",
        )
        assert fill.cash_impact() == pytest.approx(320.0)

    def test_equity_cash_impact_no_multiplier(self):
        """Regular SELL fill: no multiplier applied."""
        fill = Fill(
            fill_id="x", order_id="o", account_id="a", symbol="ANET",
            side=Side.SELL, qty=10.0, price=120.0, fee=0.0,
            fill_source="shadow", filled_at="t",
        )
        assert fill.cash_impact() == pytest.approx(1200.0)

    # ── 0205: MAX_CONTRACTS off-by-one ────────────────────────────────────────

    def test_two_contract_intent_limit_one_rejects(self):
        """open=0, requesting 2, policy limit=1 → FAIL (off-by-one fix). 0205."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 200.0, 140.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        intent = _make_option_intent(contracts=2)
        _insert_intent(conn, intent)
        dec = risk_engine.evaluate(intent, _make_policy(), _make_account(cash=9800.0), conn, strict_all=True)
        check = next(c for c in dec.checks if c.rule == "MAX_CONTRACTS_PER_SYMBOL")
        assert check.result == RuleResult.FAIL

    # ── 0206: unique order constraint ─────────────────────────────────────────

    def test_concurrent_order_creation_one_row(self):
        """Two submit_order() calls for same intent → exactly one orders row. 0206."""
        conn = _make_conn()
        intent = _make_intent()
        _insert_intent(conn, intent)
        broker = ShadowBroker(conn)
        o1 = broker.submit_order(intent)
        o2 = broker.submit_order(intent)
        assert o1.order_id == o2.order_id
        count = conn.execute("SELECT COUNT(*) FROM orders WHERE intent_id=?", (intent.intent_id,)).fetchone()[0]
        assert count == 1

    # ── 0204: risk decision provenance ───────────────────────────────────────

    def test_risk_decision_has_provenance(self):
        """Risk decision row stores uuid_id, policy_hash, and account state. 0204."""
        conn = _make_conn()
        intent = _make_intent()
        _insert_intent(conn, intent)
        policy = _make_policy()
        dec = risk_engine.evaluate(intent, policy, _make_account(), conn)
        row = conn.execute(
            "SELECT * FROM risk_decisions WHERE intent_id=?", (intent.intent_id,)
        ).fetchone()
        assert row is not None
        assert row["uuid_id"] == dec.decision_id
        assert row["policy_version"] == "1.0"
        assert row["policy_hash"] is not None
        assert row["account_cash_at_eval"] == pytest.approx(10000.0)
        assert row["account_nav_at_eval"] is not None

    # ── 0207: recommendation-driven sizing ───────────────────────────────────

    def test_target_weight_pct_sizing(self):
        """rec with target_weight_pct=2.5 → intent sized at 2.5%, not at 5% max. 0207."""
        conn = _make_conn()
        cur = conn.execute(
            "INSERT INTO recommendations (ticker, action, action_payload_json, status, created_at) VALUES (?,?,?,?,?)",
            ("ANET", "BUY", json.dumps({"price": 100.0, "target_weight_pct": 2.5}), "accepted", 0),
        )
        conn.commit()
        rec_id = cur.lastrowid
        policy = _make_policy()
        intent = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", policy, conn)
        assert intent is not None
        # NAV=$10k, target=2.5% → $250 / limit_price=101 → qty=2
        assert intent.quantity == 2.0
        # Contrast: without target_weight_pct, qty would be floor(500/101)=4

    def test_explicit_quantity_sizing(self):
        """rec with quantity=7 → intent uses exactly 7 shares regardless of weight. 0207."""
        conn = _make_conn()
        cur = conn.execute(
            "INSERT INTO recommendations (ticker, action, action_payload_json, status, created_at) VALUES (?,?,?,?,?)",
            ("ANET", "BUY", json.dumps({"price": 100.0, "quantity": 7}), "accepted", 0),
        )
        conn.commit()
        rec_id = cur.lastrowid
        intent = intent_builder.build_intent(rec_id, "AGENTIC_SHADOW_01", _make_policy(), conn)
        assert intent is not None
        assert intent.quantity == 7.0

    # ── 0201: mark-to-market NAV ─────────────────────────────────────────────

    def test_nav_uses_market_value_when_available(self):
        """_nav() uses market_value column; falls back to avg_cost when NULL. 0201."""
        conn = _make_conn()
        # Position with market_value set (higher than cost basis)
        conn.execute(
            """INSERT INTO position_snapshots
               (account_id, symbol, qty, avg_cost, instrument_type, as_of, market_price, market_value)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("AGENTIC_SHADOW_01", "ANET", 10.0, 100.0, "EQUITY", "2026-01-01", 150.0, 1500.0),
        )
        conn.commit()
        from trade_engine.risk_engine import _nav as _risk_nav
        account = _make_account(cash=9000.0)
        nav = _risk_nav(account, conn)
        assert nav == pytest.approx(10500.0)  # 9000 + 1500

    def test_nav_falls_back_to_cost_basis(self):
        """_nav() uses avg_cost×qty when market_value is NULL. 0201."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 10.0, 100.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        from trade_engine.risk_engine import _nav as _risk_nav
        account = _make_account(cash=9000.0)
        nav = _risk_nav(account, conn)
        assert nav == pytest.approx(10000.0)  # 9000 + 10*100
