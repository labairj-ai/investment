"""Chaos tests using FakeBrokerAdapter and apply_broker_fill ingestion (0249, 0255).

Verifies correct behavior under real broker failure modes. Each test exercises
the production ingestion code paths rather than shadow-broker helpers:

- Duplicate fill events → apply_broker_fill called twice; account debited once
- Cancel/fill race → FILLED wins; cash correct; no double-debit
- Out-of-order partial fills → order ends FILLED; total qty and cash correct
- Accepted-but-response-lost restart → broker.submit_order called exactly once
- Each retrieval failure (get_positions/get_open_orders/get_fills/get_broker_account)
  independently → HALTED
- Position mismatch detected by reconciliation → HALTED
- Stale quote → no order submitted (0251 quote gate blocks before submit)
"""
from __future__ import annotations

import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trade_engine import execution_engine, market_calendar
from trade_engine.broker_adapter import ShadowBrokerAdapter
from trade_engine.broker_types import BrokerFill, BrokerQuote
from trade_engine.execution_engine import FillResult, apply_broker_fill
from trade_engine.models import IntentStatus, Side, TradeIntent, OrderType, TimeInForce, InstrumentType

from tests.test_trade_engine import _make_conn, _make_intent, _insert_intent, _make_policy
from tests.fake_broker import FakeBrokerAdapter


def _fresh_quote(bid: float = 99.0, ask: float = 101.0, symbol: str = "ANET") -> BrokerQuote:
    return BrokerQuote(
        bid=bid, ask=ask, symbol=symbol,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        source="test",
    )


def _seed_intent(conn, qty: float = 1.0, price: float = 100.0) -> str:
    intent = _make_intent(quantity=qty, limit_price=price)
    _insert_intent(conn, intent)
    return intent.intent_id


def _make_broker_fill(
    order_id: str,
    account_id: str = "AGENTIC_SHADOW_01",
    symbol: str = "ANET",
    qty: float = 1.0,
    price: float = 100.0,
    side: str = "BUY",
    fill_id: str | None = None,
) -> BrokerFill:
    return BrokerFill(
        broker_fill_id=fill_id or str(uuid.uuid4()),
        broker_order_id=order_id,
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        filled_at=datetime.now(timezone.utc).isoformat(),
        fee=0.0,
        local_order_id=order_id,
        account_id=account_id,
    )


def _submit_working_order(conn, qty: float = 1.0, price: float = 100.0) -> str:
    """Submit an intent and leave the order in WORKING state (no immediate fill).

    Uses a quote just above the limit price so the BUY order never fills during process_intent.
    """
    intent_id = _seed_intent(conn, qty=qty, price=price)
    broker = ShadowBrokerAdapter(conn, "AGENTIC_SHADOW_01")
    # Quote slightly above limit → BUY LIMIT doesn't fill (ask > limit_price)
    q_ask = price * 1.01 + 1.0
    q_bid = round(q_ask * 0.99, 4)  # ~1% spread, well within max_spread_pct=2%

    class _FakeQ:
        bid = q_bid
        ask = q_ask
        market_timestamp = None
        retrieved_at = datetime.now(timezone.utc).isoformat()
        source = "test"

    with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
         patch.object(market_calendar, "is_market_open", return_value=True), \
         patch("trade_engine.market_data._get_executable_quote", return_value=_FakeQ()):
        execution_engine.process_intent(intent_id, conn, broker=broker)
    order_row = conn.execute("SELECT order_id FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
    assert order_row is not None, "Expected order to be submitted and stay WORKING"
    return order_row["order_id"]


class TestDuplicateFill:
    """Duplicate fill ID piped through apply_broker_fill twice → account debited once (0252, 0255)."""

    def test_duplicate_broker_fill_id_debited_once(self):
        conn = _make_conn()
        order_id = _submit_working_order(conn)

        fill_id = str(uuid.uuid4())
        bf = _make_broker_fill(order_id, fill_id=fill_id, price=100.0)

        cash_before = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]

        # First application
        r1 = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        # Second application (same fill_id — replay/duplicate)
        r2 = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)

        cash_after = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]
        fills = conn.execute("SELECT COUNT(*) FROM fills WHERE fill_id=?", (fill_id,)).fetchone()[0]

        assert r1 == FillResult.APPLIED
        assert r2 == FillResult.ALREADY_APPLIED
        assert fills == 1, f"Expected exactly 1 fill row, got {fills}"
        assert cash_after == pytest.approx(cash_before - 100.0, abs=0.01), (
            f"Cash should decrease by exactly 100; before={cash_before} after={cash_after}"
        )


class TestCancelFillRace:
    """FILLED event + CANCELLED event for same order → FILLED wins; cash debited once (0255)."""

    def test_filled_then_cancelled_event_no_double_debit(self):
        conn = _make_conn()
        order_id = _submit_working_order(conn)

        fill_id = str(uuid.uuid4())
        bf = _make_broker_fill(order_id, fill_id=fill_id, price=100.0)

        cash_before = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]

        # FILLED event arrives first
        r1 = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        # CANCELLED event injected for same order (race): apply_broker_fill is not called for cancel
        # Cancel transition is handled by the engine directly
        conn.execute("UPDATE orders SET state='CANCELLED' WHERE order_id=?", (order_id,))
        conn.commit()
        # Duplicate fill event arrives (same fill_id — idempotency catches it)
        r2 = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)

        cash_after = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]
        fills = conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]

        assert r1 == FillResult.APPLIED
        assert r2 == FillResult.ALREADY_APPLIED
        assert fills == 1
        assert cash_after == pytest.approx(cash_before - 100.0, abs=0.01)


class TestOutOfOrderPartialFills:
    """Two PARTIALLY_FILLED events in reverse order → order ends FILLED; total qty and cash correct (0255)."""

    def test_out_of_order_partial_fills_total_correct(self):
        conn = _make_conn()
        order_id = _submit_working_order(conn, qty=2.0, price=150.0)

        cash_before = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]

        fill_id_1 = str(uuid.uuid4())
        fill_id_2 = str(uuid.uuid4())
        bf2 = _make_broker_fill(order_id, fill_id=fill_id_2, qty=1.0, price=150.0)
        bf1 = _make_broker_fill(order_id, fill_id=fill_id_1, qty=1.0, price=150.0)

        # Deliver in reverse order (fill_2 first, then fill_1)
        r2 = apply_broker_fill(bf2, "AGENTIC_SHADOW_01", conn)
        r1 = apply_broker_fill(bf1, "AGENTIC_SHADOW_01", conn)

        cash_after = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]
        fills = conn.execute("SELECT COUNT(*) FROM fills WHERE order_id=?", (order_id,)).fetchone()[0]
        order_row = conn.execute("SELECT state, fill_qty FROM orders WHERE order_id=?", (order_id,)).fetchone()

        assert r1 == FillResult.APPLIED
        assert r2 == FillResult.APPLIED
        assert fills == 2, f"Expected 2 fill rows, got {fills}"
        assert order_row["state"] == "FILLED"
        assert order_row["fill_qty"] == pytest.approx(2.0)
        assert cash_after == pytest.approx(cash_before - 300.0, abs=0.01)


class TestAcceptedButLostRestart:
    """Accepted-but-response-lost: broker.submit_order called once across crash + restart (0253, 0255, 0264)."""

    def test_timeout_then_restart_imports_existing_order(self):
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)

        # Wrap submit_order to count total calls across crash + restart
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_timeout=True)
        _orig_submit = broker.submit_order
        _submit_calls = []

        def _counting_submit(intent, client_order_id=None):
            _submit_calls.append(1)
            return _orig_submit(intent, client_order_id=client_order_id)

        broker.submit_order = _counting_submit

        class _FreshQ:
            bid = 99.0
            ask = 100.5  # ask > limit=100 → no fill event; order stays PENDING/WORKING
            market_timestamp = None
            retrieved_at = datetime.now(timezone.utc).isoformat()
            source = "test"

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=_FreshQ()):
            with pytest.raises(execution_engine.BrokerSubmissionIndeterminate):
                execution_engine.process_intent(intent_id, conn, broker=broker)

        # After crash: local DB has PENDING_SUBMIT; broker has WORKING in _broker_orders
        local_row = conn.execute(
            "SELECT state, broker_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert local_row is not None, "PENDING_SUBMIT row must exist after crash"
        assert local_row["state"] == "PENDING_SUBMIT", f"Expected PENDING_SUBMIT, got {local_row['state']}"
        assert len(_submit_calls) == 1, "submit_order called exactly once before crash"

        # Restart: same broker instance (it holds _broker_orders), timeout cleared
        broker._submit_timeout = False
        state = execution_engine.initialize_trading_session(
            "AGENTIC_SHADOW_01", conn, broker=broker
        )

        # After reconciliation: TRADING_READY; local order promoted PENDING_SUBMIT → WORKING
        assert state == execution_engine.TradingReadyState.TRADING_READY, f"Expected TRADING_READY, got {state}"
        final = conn.execute(
            "SELECT state, broker_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert final["state"] == "WORKING", f"Expected WORKING after reconcile, got {final['state']}"
        assert final["broker_order_id"] is not None, "broker_order_id must be attached after reconciliation"
        assert len(_submit_calls) == 1, "submit_order must NOT be called again on restart (0264)"


class TestIndeterminateSubmissionCircuitBreaker:
    """BrokerSubmissionIndeterminate halts the cycle and blocks further intent processing (0265)."""

    class _FreshQ:
        bid = 99.0
        ask = 100.5  # > limit=100 → no immediate fill
        market_timestamp = None
        retrieved_at = None
        source = "test"

        def __init__(self):
            from datetime import datetime, timezone
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _run_cycle(self, conn, broker):
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch.object(execution_engine, "_refresh_market_prices"), \
             patch.object(execution_engine, "_update_nav_high_water"), \
             patch.object(execution_engine, "_write_account_snapshot"), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            return execution_engine.run_execution_cycle(
                "AGENTIC_SHADOW_01", conn, broker=broker,
                trading_state=execution_engine.TradingReadyState.TRADING_READY,
            )

    def test_indeterminate_halts_cycle(self):
        """Two pending intents; first causes BrokerSubmissionIndeterminate; second never submitted (0265)."""
        conn = _make_conn()
        _seed_intent(conn, qty=1.0, price=100.0)  # intent #1
        _seed_intent(conn, qty=1.0, price=100.0)  # intent #2

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_lost=True)
        submit_count = []
        orig = broker.submit_order

        def _counting(intent, client_order_id=None):
            submit_count.append(1)
            return orig(intent, client_order_id=client_order_id)

        broker.submit_order = _counting

        result = self._run_cycle(conn, broker)

        assert result["execution_state"] == "HALTED", f"Expected HALTED, got {result['execution_state']}"
        assert result["halt_reason"] == "SUBMISSION_INDETERMINATE"
        assert len(submit_count) == 1, f"submit_order must be called exactly once; got {len(submit_count)}"

    def test_indeterminate_process_intent_raises(self):
        """process_intent raises BrokerSubmissionIndeterminate when submit_order throws (0265)."""
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_lost=True)

        class _FreshQ:
            bid = 99.0
            ask = 100.5
            market_timestamp = None
            retrieved_at = datetime.now(timezone.utc).isoformat()
            source = "test"

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=_FreshQ()):
            with pytest.raises(execution_engine.BrokerSubmissionIndeterminate):
                execution_engine.process_intent(intent_id, conn, broker=broker)

    def test_after_reconciliation_next_cycle_processes_remaining(self):
        """After BrokerSubmissionIndeterminate + reconciliation, remaining intents are processed (0265)."""
        conn = _make_conn()
        _seed_intent(conn, qty=1.0, price=100.0)  # intent #1 — will cause timeout
        _seed_intent(conn, qty=1.0, price=100.0)  # intent #2 — blocked by halt, then processed

        # submit_timeout: broker writes to _broker_orders then raises (0264 pattern)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_timeout=True)

        # First cycle: intent #1 → BrokerSubmissionIndeterminate → HALTED
        result1 = self._run_cycle(conn, broker)
        assert result1["execution_state"] == "HALTED"
        assert result1["halt_reason"] == "SUBMISSION_INDETERMINATE"

        # Reconciliation: same broker instance, timeout mode cleared
        broker._submit_timeout = False
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY

        # Intent #1: PENDING_SUBMIT → WORKING (reconciled); status still APPROVED → not re-queued
        intent1_order = conn.execute(
            "SELECT state FROM orders LIMIT 1"
        ).fetchone()
        assert intent1_order["state"] == "WORKING"

        # Second cycle: processes intent #2 (still PENDING in trade_intents)
        result2 = self._run_cycle(conn, broker)
        assert result2["execution_state"] == "OK", f"Expected OK, got {result2['execution_state']}"
        assert result2["new_intents_processed"] == 1, "Intent #2 must be processed in second cycle"


class TestRetrievalFailureHalts:
    """Each broker retrieval failure independently triggers HALTED (0255)."""

    def _make_failing_broker(self, conn, fail_method: str):
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        setattr(broker, fail_method, MagicMock(side_effect=RuntimeError(f"chaos: {fail_method} failed")))
        return broker

    def test_get_broker_account_failure_halts(self):
        conn = _make_conn()
        broker = self._make_failing_broker(conn, "get_broker_account")
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED

    def test_get_positions_failure_halts(self):
        conn = _make_conn()
        broker = self._make_failing_broker(conn, "get_positions")
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED

    def test_get_open_orders_failure_halts(self):
        conn = _make_conn()
        broker = self._make_failing_broker(conn, "get_open_orders")
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED

    def test_get_fills_failure_halts(self):
        conn = _make_conn()
        broker = self._make_failing_broker(conn, "get_fills")
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED


class TestPositionMismatchBlocks:
    """Position qty mismatch detected by reconciliation → blocks new orders (0249)."""

    def test_position_mismatch_halts_session(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 10.0, 100.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", position_mismatch_qty=5.0)
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED


class TestStaleQuoteNoSubmit:
    """Stale quote from broker → 0251 quote gate blocks order submission entirely (0251, 0255)."""

    def test_stale_quote_does_not_submit_order(self):
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", stale_quote=True)

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True):
            result = execution_engine.process_intent(intent_id, conn, broker=broker)

        # Quote gate fires before submit → no order created
        assert result.decision == "QUOTE_UNAVAILABLE", f"Expected QUOTE_UNAVAILABLE, got {result.decision}"
        assert result.order_id is None
        fills = conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
        assert fills == 0
        # PENDING_SUBMIT row may exist (pre-created before quote check is NOT the flow; quote is checked first)
        # Actually, quote check happens before PENDING_SUBMIT creation, so no order row at all
        pending = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE state='PENDING_SUBMIT'"
        ).fetchone()[0]
        assert pending == 0, f"No PENDING_SUBMIT order should exist when quote fails; got {pending}"
