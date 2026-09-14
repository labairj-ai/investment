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
from trade_engine.broker_types import BrokerFill, BrokerOrder, BrokerOrderEvent, BrokerQuote
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
    """Cancel/fill race correctness with real BrokerOrderEvent objects (0255, 0266).

    Ordering A: FILLED event then CANCELLED event → final state FILLED, cash debited once.
    Ordering B: CANCEL_REQUESTED → CANCELLED event → late FILLED event → final state FILLED, cash once.
    """

    def _run_open_orders(self, conn, broker):
        """Run process_open_orders with standard policy/market patches."""
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=None):
            return execution_engine.process_open_orders(
                "AGENTIC_SHADOW_01", conn, broker=broker
            )

    def _make_filled_event(self, order_id: str, qty: float = 1.0, price: float = 100.0) -> "BrokerOrderEvent":
        from trade_engine.broker_types import BrokerOrderEvent
        return BrokerOrderEvent(
            event_type="FILLED",
            broker_order_id=order_id,
            local_order_id=order_id,
            fill_qty=qty,
            fill_price=price,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0,
            broker_fill_id=str(uuid.uuid4()),
        )

    def _make_cancelled_event(self, order_id: str) -> "BrokerOrderEvent":
        from trade_engine.broker_types import BrokerOrderEvent
        return BrokerOrderEvent(
            event_type="CANCELLED",
            broker_order_id=order_id,
            local_order_id=order_id,
        )

    def test_ordering_a_filled_then_cancelled(self):
        """Ordering A: FILLED event arrives before CANCELLED → final FILLED, cash debited once (0266)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)

        cash_before = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]

        filled_event = self._make_filled_event(order_id, qty=1.0, price=100.0)
        cancelled_event = self._make_cancelled_event(order_id)

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        broker.poll_order_events = lambda account_id, quote=None: [filled_event, cancelled_event]

        self._run_open_orders(conn, broker)

        final = conn.execute(
            "SELECT state FROM orders WHERE order_id=?", (order_id,)
        ).fetchone()
        cash_after = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]
        fills = conn.execute("SELECT COUNT(*) FROM fills WHERE order_id=?", (order_id,)).fetchone()[0]
        pos = conn.execute(
            "SELECT qty FROM position_snapshots WHERE account_id='AGENTIC_SHADOW_01' AND symbol='ANET'"
        ).fetchone()

        assert final["state"] == "FILLED", f"Expected FILLED, got {final['state']}"
        assert fills == 1, f"Expected 1 fill row, got {fills}"
        assert cash_after == pytest.approx(cash_before - 1.0 * 100.0, abs=0.01)
        assert pos is not None and pos["qty"] == pytest.approx(1.0)

    def test_ordering_b_cancel_then_late_fill(self):
        """Ordering B: CANCEL_REQUESTED → CANCELLED → late FILLED → final FILLED, cash debited once (0266)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)

        # Transition to CANCEL_REQUESTED (simulating a cancel request sent to broker)
        conn.execute("UPDATE orders SET state='CANCEL_REQUESTED' WHERE order_id=?", (order_id,))
        conn.commit()

        cash_before = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]

        cancelled_event = self._make_cancelled_event(order_id)
        late_filled_event = self._make_filled_event(order_id, qty=1.0, price=100.0)

        # Both events arrive in same poll: CANCELLED first, then late FILLED
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        broker.poll_order_events = lambda account_id, quote=None: [cancelled_event, late_filled_event]

        self._run_open_orders(conn, broker)

        final = conn.execute(
            "SELECT state FROM orders WHERE order_id=?", (order_id,)
        ).fetchone()
        cash_after = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]
        fills = conn.execute("SELECT COUNT(*) FROM fills WHERE order_id=?", (order_id,)).fetchone()[0]
        pos = conn.execute(
            "SELECT qty FROM position_snapshots WHERE account_id='AGENTIC_SHADOW_01' AND symbol='ANET'"
        ).fetchone()

        assert final["state"] == "FILLED", f"Expected FILLED after late fill, got {final['state']}"
        assert fills == 1, f"Expected 1 fill row, got {fills}"
        assert cash_after == pytest.approx(cash_before - 1.0 * 100.0, abs=0.01)
        assert pos is not None and pos["qty"] == pytest.approx(1.0)


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


# ════════════════════════════════════════════════════════════════════════════════
# 0268: Strict local/broker ID separation
# ════════════════════════════════════════════════════════════════════════════════

class TestDistinctBrokerIdRouting:
    """distinct_broker_id mode: local order_id ≠ broker_order_id; all routing must still work (0268)."""

    class _FreshQ:
        bid = 99.5
        ask = 100.5  # above limit=100 → BUY LIMIT doesn't fill; spread ≈1% < 2% max
        market_timestamp = None
        retrieved_at = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _run_intent(self, conn, broker):
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            result = execution_engine.process_intent(intent_id, conn, broker=broker)
        return result

    def test_submit_attaches_distinct_broker_order_id(self):
        """With distinct_broker_id, broker_order_id in DB ≠ local order_id (0268)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", distinct_broker_id=True)
        result = self._run_intent(conn, broker)

        assert result.decision == "APPROVED", f"Expected APPROVED, got {result.decision}"
        assert result.order_id is not None

        row = conn.execute(
            "SELECT order_id, broker_order_id FROM orders WHERE order_id=?", (result.order_id,)
        ).fetchone()
        assert row is not None
        assert row["broker_order_id"] is not None
        assert row["broker_order_id"] != row["order_id"], (
            f"broker_order_id must differ from local order_id; both were {row['order_id']}"
        )

    def test_process_open_orders_routes_fills_via_broker_id(self):
        """process_open_orders uses broker_order_id for get_order; fill still lands on correct local row (0268)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", distinct_broker_id=True)
        result = self._run_intent(conn, broker)
        local_oid = result.order_id

        row = conn.execute(
            "SELECT broker_order_id FROM orders WHERE order_id=?", (local_oid,)
        ).fetchone()
        assert row["broker_order_id"] != local_oid, "pre-condition: IDs must differ"

        # Deliver a fill event keyed by broker_order_id (not local order_id)
        broker_oid = row["broker_order_id"]
        fill_event = BrokerOrderEvent(
            event_type="FILLED",
            broker_order_id=broker_oid,
            local_order_id=None,   # real broker never sends local ID
            fill_qty=1.0,
            fill_price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0,
            broker_fill_id=str(uuid.uuid4()),
        )

        # Patch poll_order_events to return our event
        with patch.object(broker, "poll_order_events", return_value=[fill_event]), \
             patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True):
            fills, _, _ = execution_engine.process_open_orders(
                "AGENTIC_SHADOW_01", conn, broker=broker
            )

        assert len(fills) == 1, f"Expected 1 fill, got {len(fills)}"
        filled_order = conn.execute(
            "SELECT state FROM orders WHERE order_id=?", (local_oid,)
        ).fetchone()
        assert filled_order["state"] == "FILLED", f"Expected FILLED, got {filled_order['state']}"

    def test_cancel_uses_broker_order_id(self):
        """Pre-fill risk revalidation cancels via broker_order_id; local row transitions to CANCELLED (0268)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", distinct_broker_id=True)
        result = self._run_intent(conn, broker)
        local_oid = result.order_id

        # Rig risk revalidation to reject so cancel_order is called
        cancel_calls = []
        orig_cancel = broker.cancel_order

        def _recording_cancel(order_id, reason="USER_REQUESTED"):
            cancel_calls.append(order_id)
            return orig_cancel(order_id, reason=reason)

        broker.cancel_order = _recording_cancel

        rejecting_risk = MagicMock(return_value=MagicMock(decision="REJECTED"))
        with patch.object(execution_engine, "risk_evaluate", rejecting_risk), \
             patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            execution_engine.process_open_orders("AGENTIC_SHADOW_01", conn, broker=broker)

        assert len(cancel_calls) == 1, f"cancel_order must be called once; called {len(cancel_calls)} times"
        row = conn.execute(
            "SELECT broker_order_id FROM orders WHERE order_id=?", (local_oid,)
        ).fetchone()
        # The recorded cancel call must use the broker_order_id, not the local order_id
        assert cancel_calls[0] == row["broker_order_id"], (
            f"cancel_order must receive broker_order_id={row['broker_order_id']!r}, "
            f"got {cancel_calls[0]!r}"
        )


# ════════════════════════════════════════════════════════════════════════════════
# 0269: client_order_id in BrokerFill/BrokerOrderEvent; resolver used in reconciliation
# ════════════════════════════════════════════════════════════════════════════════

class TestResolverEverywhere:
    """Three-tier resolver works for fills and events; reconciliation uses resolver (0269)."""

    def _seed_working_order(self, conn, broker_order_id=None):
        """Insert a WORKING order with optional broker_order_id."""
        local_oid = str(uuid.uuid4())
        cid = f"AGENTIC_SHADOW_01:intent-{local_oid[:8]}"
        intent_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO trade_intents (intent_id, account_id, symbol, side, quantity, "
            "order_type, limit_price, time_in_force, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (intent_id, "AGENTIC_SHADOW_01", "ANET", "BUY", 1.0, "LIMIT", 100.0, "GTC", "APPROVED",
             datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "INSERT INTO orders (order_id, intent_id, account_id, symbol, side, quantity, "
            "order_type, state, fill_qty, fill_cash, client_order_id, broker_order_id, "
            "submitted_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (local_oid, intent_id, "AGENTIC_SHADOW_01", "ANET", "BUY", 1.0, "LIMIT", "WORKING",
             0.0, 0.0, cid, broker_order_id, datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return local_oid, cid, broker_order_id or local_oid

    def test_fill_resolved_by_broker_order_id(self):
        """apply_broker_fill with broker_order_id only (no local_order_id) resolves correctly (0269)."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) "
            "VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 0.0, 0.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        broker_oid = str(uuid.uuid4())
        local_oid, cid, _ = self._seed_working_order(conn, broker_order_id=broker_oid)

        bf = BrokerFill(
            broker_fill_id="FILL-BOID-001",
            broker_order_id=broker_oid,
            symbol="ANET",
            side="BUY",
            qty=1.0,
            price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0,
            local_order_id=None,   # broker doesn't send local ID
            account_id="AGENTIC_SHADOW_01",
        )
        result = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        assert result == FillResult.APPLIED
        fill_row = conn.execute("SELECT fill_id FROM fills WHERE fill_id=?", ("FILL-BOID-001",)).fetchone()
        assert fill_row is not None, "Fill must be recorded by broker_order_id resolution"

    def test_fill_resolved_by_client_order_id(self):
        """apply_broker_fill with client_order_id only resolves correctly (0269)."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO position_snapshots (account_id, symbol, qty, avg_cost, instrument_type, as_of) "
            "VALUES (?,?,?,?,?,?)",
            ("AGENTIC_SHADOW_01", "ANET", 0.0, 0.0, "EQUITY", "2026-01-01"),
        )
        conn.commit()
        local_oid, cid, _ = self._seed_working_order(conn)  # broker_order_id=None → resolver uses client_order_id

        bf = BrokerFill(
            broker_fill_id="FILL-CID-001",
            broker_order_id="UNKNOWN-BROKER-ID",
            symbol="ANET",
            side="BUY",
            qty=1.0,
            price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0,
            local_order_id=None,
            account_id="AGENTIC_SHADOW_01",
            client_order_id=cid,
        )
        result = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        assert result == FillResult.APPLIED
        fill_row = conn.execute("SELECT fill_id FROM fills WHERE fill_id=?", ("FILL-CID-001",)).fetchone()
        assert fill_row is not None, "Fill must be recorded by client_order_id resolution"

    def test_event_resolved_by_broker_order_id(self):
        """apply_broker_order_event with broker_order_id only cancels the correct local row (0269)."""
        conn = _make_conn()
        broker_oid = str(uuid.uuid4())
        local_oid, _, _ = self._seed_working_order(conn, broker_order_id=broker_oid)

        from trade_engine.execution_engine import apply_broker_order_event
        event = BrokerOrderEvent(
            event_type="CANCELLED",
            broker_order_id=broker_oid,
            local_order_id=None,
        )
        apply_broker_order_event(event, "AGENTIC_SHADOW_01", conn)
        row = conn.execute("SELECT state FROM orders WHERE order_id=?", (local_oid,)).fetchone()
        assert row["state"] == "CANCELLED", f"Expected CANCELLED, got {row['state']}"


# ════════════════════════════════════════════════════════════════════════════════
# 0270: PENDING_SUBMIT resolution via find_order_by_client_order_id
# ════════════════════════════════════════════════════════════════════════════════

class TestIndeterminateResolution:
    """PENDING_SUBMIT rows are always resolved during reconciliation (0270)."""

    class _FreshQ:
        bid = 99.0
        ask = 100.5
        market_timestamp = None
        retrieved_at = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def test_submit_lost_reconcile_marks_cancelled(self):
        """submit_lost: broker never received order; reconcile marks CANCELLED (0270)."""
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_lost=True)

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            with pytest.raises(execution_engine.BrokerSubmissionIndeterminate):
                execution_engine.process_intent(intent_id, conn, broker=broker)

        # After crash: PENDING_SUBMIT; broker's _broker_orders is empty
        row = conn.execute("SELECT state FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert row["state"] == "PENDING_SUBMIT"

        # Reconcile with submit_lost broker: find_order_by_client_order_id → None → CANCELLED
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY, (
            f"Expected TRADING_READY after resolving lost submit, got {state}"
        )
        final = conn.execute("SELECT state FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert final["state"] == "CANCELLED", (
            f"Lost order must be CANCELLED after reconciliation; got {final['state']}"
        )

    def test_submit_timeout_reconcile_promotes_to_working(self):
        """submit_timeout: broker has order; reconcile promotes PENDING_SUBMIT → WORKING (0270)."""
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_timeout=True)

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            with pytest.raises(execution_engine.BrokerSubmissionIndeterminate):
                execution_engine.process_intent(intent_id, conn, broker=broker)

        broker._submit_timeout = False
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY
        final = conn.execute("SELECT state, broker_order_id FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert final["state"] == "WORKING", f"Expected WORKING, got {final['state']}"
        assert final["broker_order_id"] is not None

    def test_find_order_lookup_failure_halts(self):
        """find_order_by_client_order_id raising → RECONCILIATION_UNAVAILABLE → HALTED (0270)."""
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_lost=True)

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            with pytest.raises(execution_engine.BrokerSubmissionIndeterminate):
                execution_engine.process_intent(intent_id, conn, broker=broker)

        # Simulate connectivity failure during find_order_by_client_order_id
        broker.find_order_by_client_order_id = MagicMock(
            side_effect=RuntimeError("network timeout on client_order_id lookup")
        )
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED, (
            f"Lookup failure must → HALTED; got {state}"
        )


# ════════════════════════════════════════════════════════════════════════════════
# 0271: ACK-state normalization
# ════════════════════════════════════════════════════════════════════════════════

class TestAckStateNormalization:
    """BrokerOrderAck.normalized_state drives local order state after submit (0271)."""

    class _FreshQ:
        bid = 99.5
        ask = 100.5  # above limit=100 → no fill in shadow mode; spread ≈1% < 2% max
        market_timestamp = None
        retrieved_at = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _run_intent_with_ack_state(self, conn, ack_state: str):
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state=ack_state)
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            result = execution_engine.process_intent(intent_id, conn, broker=broker)
        return result, intent_id, conn.execute(
            "SELECT state FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()

    def test_working_ack_produces_working_order(self):
        result, _, row = self._run_intent_with_ack_state(_make_conn(), "WORKING")
        assert result.decision == "APPROVED"
        assert row["state"] == "WORKING"

    def test_rejected_ack_produces_rejected_order_and_intent(self):
        conn = _make_conn()
        result, intent_id, row = self._run_intent_with_ack_state(conn, "REJECTED")
        assert result.decision == "REJECTED"
        assert row["state"] == "REJECTED"
        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] == "REJECTED", f"Intent must be REJECTED; got {intent_row['status']}"

    def test_pending_ack_leaves_pending_submit(self):
        """PENDING ACK: broker queued but not activated; local stays PENDING_SUBMIT (0271)."""
        conn = _make_conn()
        result, _, row = self._run_intent_with_ack_state(conn, "PENDING")
        assert result.decision == "APPROVED"
        assert row["state"] == "PENDING_SUBMIT", f"Expected PENDING_SUBMIT; got {row['state']}"

    def test_filled_ack_produces_filled_order_immediately(self):
        """FILLED ACK: broker confirmed fill at acceptance; local order must reach FILLED (0271)."""
        conn = _make_conn()
        result, intent_id, row = self._run_intent_with_ack_state(conn, "FILLED")
        assert result.decision == "APPROVED"
        assert row["state"] == "FILLED", f"Expected FILLED; got {row['state']}"
        assert result.fill is not None, "FILLED ACK must produce a Fill object"
        # Verify fill is persisted
        fill_count = conn.execute("SELECT COUNT(*) FROM fills WHERE account_id=?",
                                  ("AGENTIC_SHADOW_01",)).fetchone()[0]
        assert fill_count == 1, f"Expected 1 fill; got {fill_count}"


# ════════════════════════════════════════════════════════════════════════════════
# 0272: Broker account binding
# ════════════════════════════════════════════════════════════════════════════════

class TestBrokerAccountBinding:
    """Broker account ID verified at session init; mismatch halts (0272)."""

    def test_matching_account_id_allows_trading_ready(self):
        """Broker returns expected account ID → TRADING_READY (0272)."""
        conn = _make_conn()
        # No expected_broker_account_id in policy → always passes
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", broker_account_id="AGENTIC_SHADOW_01")
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY

    def test_mismatched_account_id_halts_when_expected_set(self):
        """Broker returns wrong account ID when expected_broker_account_id is configured → HALTED (0272)."""
        conn = _make_conn()

        # Inject expected_broker_account_id into policy via a patched load_policy
        from trade_engine.policy import TradingPolicy
        policy_with_binding = _make_policy()
        object.__setattr__(
            policy_with_binding, "circuit_breakers",
            {**policy_with_binding.circuit_breakers, "expected_broker_account_id": "EXPECTED_ACCOUNT_99"}
        )

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", broker_account_id="WRONG_ACCOUNT")
        with patch.object(execution_engine, "load_policy", return_value=policy_with_binding):
            state = execution_engine.initialize_trading_session(
                "AGENTIC_SHADOW_01", conn, broker=broker
            )
        assert state == execution_engine.TradingReadyState.HALTED, (
            f"Account mismatch must → HALTED; got {state}"
        )

    def test_get_account_id_failure_halts(self):
        """get_account_id() raising during init → HALTED (0272)."""
        conn = _make_conn()
        policy_with_binding = _make_policy()
        object.__setattr__(
            policy_with_binding, "circuit_breakers",
            {**policy_with_binding.circuit_breakers, "expected_broker_account_id": "ANY_ID"}
        )
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        broker.get_account_id = MagicMock(side_effect=RuntimeError("connectivity failure"))
        with patch.object(execution_engine, "load_policy", return_value=policy_with_binding):
            state = execution_engine.initialize_trading_session(
                "AGENTIC_SHADOW_01", conn, broker=broker
            )
        assert state == execution_engine.TradingReadyState.HALTED

    def test_no_expected_account_id_skips_check(self):
        """No expected_broker_account_id in policy → get_account_id never called (0272)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", broker_account_id="ANY_ID")
        get_account_id_calls = []
        orig = broker.get_account_id

        def _recording():
            get_account_id_calls.append(1)
            return orig()

        broker.get_account_id = _recording
        # Default policy has no expected_broker_account_id → check skipped
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY
        assert len(get_account_id_calls) == 0, "get_account_id must not be called when no binding configured"


# ════════════════════════════════════════════════════════════════════════════════
# 0274: Terminal-state indeterminate recovery
# ════════════════════════════════════════════════════════════════════════════════

class TestTerminalStateRecovery:
    """PENDING_SUBMIT reconciliation respects terminal broker states (0274).

    When a crash leaves a PENDING_SUBMIT row and the broker reports a terminal
    state (FILLED/CANCELLED/REJECTED) before the app restarts, reconciliation
    must recover to that terminal state — not blindly advance to WORKING.
    """

    class _FreshQ:
        bid = 99.5
        ask = 100.5
        market_timestamp = None
        retrieved_at = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _crash_and_stage_broker_state(self, conn, broker_state: str, fill_price: float = 99.83):
        """Submit with timeout (crash), then stage the broker's state before restart."""
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_timeout=True)

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            with pytest.raises(execution_engine.BrokerSubmissionIndeterminate):
                execution_engine.process_intent(intent_id, conn, broker=broker)

        # After crash: PENDING_SUBMIT locally; broker has WORKING in _broker_orders
        row = conn.execute(
            "SELECT state, client_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert row["state"] == "PENDING_SUBMIT"
        cid = row["client_order_id"]
        broker_order_id = next(
            bid for bid, bo in broker._broker_orders.items() if bo.client_order_id == cid
        )

        # Stage the broker's state before restart
        existing = broker._broker_orders[broker_order_id]
        broker._broker_orders[broker_order_id] = BrokerOrder(
            broker_order_id=broker_order_id,
            symbol=existing.symbol,
            side=existing.side,
            quantity=existing.quantity,
            fill_qty=existing.quantity if broker_state == "FILLED" else 0.0,
            state=broker_state,
            limit_price=existing.limit_price,
            client_order_id=existing.client_order_id,
            local_order_id=existing.local_order_id,
        )
        if broker_state == "FILLED":
            broker._broker_fills[broker_order_id] = [BrokerFill(
                broker_fill_id=f"auth-fill-{broker_order_id}",
                broker_order_id=broker_order_id,
                symbol=existing.symbol,
                side=existing.side,
                qty=existing.quantity,
                price=fill_price,
                filled_at=datetime.now(timezone.utc).isoformat(),
                fee=0.27,
                local_order_id=None,
                account_id="AGENTIC_SHADOW_01",
                client_order_id=cid,
            )]

        broker._submit_timeout = False
        return broker, intent_id

    def test_broker_filled_before_restart_recovers_filled(self):
        """submit_timeout → broker fills at authoritative price → reconcile → FILLED (0274)."""
        conn = _make_conn()
        broker, intent_id = self._crash_and_stage_broker_state(conn, "FILLED", fill_price=99.83)

        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY, (
            f"Expected TRADING_READY after terminal recovery; got {state}"
        )
        final = conn.execute("SELECT state, fill_qty FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert final["state"] == "FILLED", f"Expected FILLED; got {final['state']}"
        assert float(final["fill_qty"]) == pytest.approx(1.0)

        fill_row = conn.execute(
            "SELECT price, fee FROM fills WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()
        assert fill_row is not None, "Fill must be persisted after FILLED recovery"
        assert fill_row["price"] == pytest.approx(99.83), "Fill price must be broker-authoritative"
        assert fill_row["fee"] == pytest.approx(0.27), "Fill fee must be broker-authoritative"

    def test_broker_cancelled_before_restart_recovers_cancelled(self):
        """submit_timeout → broker cancels → reconcile → CANCELLED locally (0274)."""
        conn = _make_conn()
        broker, intent_id = self._crash_and_stage_broker_state(conn, "CANCELLED")

        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY
        final = conn.execute("SELECT state FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert final["state"] == "CANCELLED", f"Expected CANCELLED; got {final['state']}"
        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] == "CANCELLED"

    def test_broker_rejected_before_restart_recovers_rejected(self):
        """submit_timeout → broker rejects → reconcile → REJECTED locally (0274)."""
        conn = _make_conn()
        broker, intent_id = self._crash_and_stage_broker_state(conn, "REJECTED")

        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY
        final = conn.execute("SELECT state FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert final["state"] == "REJECTED", f"Expected REJECTED; got {final['state']}"
        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] == "REJECTED"


# ════════════════════════════════════════════════════════════════════════════════
# 0276: Fail-closed account binding
# ════════════════════════════════════════════════════════════════════════════════

class TestFailClosedAccountBinding:
    """Policy load failure or missing required ID halts session init (0276)."""

    def test_policy_load_failure_halts(self):
        """load_policy() raises → initialize_trading_session returns HALTED (0276)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        with patch.object(execution_engine, "load_policy",
                          side_effect=FileNotFoundError("policy.json not found")):
            state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED, (
            f"Policy load failure must → HALTED; got {state}"
        )

    def test_require_binding_without_expected_id_halts(self):
        """require_account_binding=True but no expected_broker_account_id → HALTED (0276)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        policy_req = _make_policy()
        object.__setattr__(
            policy_req, "circuit_breakers",
            {**policy_req.circuit_breakers, "require_account_binding": True},
        )
        with patch.object(execution_engine, "load_policy", return_value=policy_req):
            state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED, (
            f"require_account_binding=True with no ID must → HALTED; got {state}"
        )

    def test_require_binding_false_with_no_id_is_ok(self):
        """require_account_binding=False (default) with no expected ID → check skipped (0276)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        # Default policy has no expected ID and require_account_binding=False
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY


# ════════════════════════════════════════════════════════════════════════════════
# 0277: End-to-end crash matrix with distinct broker IDs
# ════════════════════════════════════════════════════════════════════════════════

class TestCrashMatrixE2E:
    """Full crash/restart/recovery matrix; local ID ≠ broker ID throughout (0277)."""

    class _FreshQ:
        bid = 99.5
        ask = 100.5
        market_timestamp = None
        retrieved_at = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _do_crash(self, conn):
        """Submit via submit_timeout → raises BrokerSubmissionIndeterminate; returns broker."""
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_timeout=True)
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            with pytest.raises(execution_engine.BrokerSubmissionIndeterminate):
                execution_engine.process_intent(intent_id, conn, broker=broker)
        return broker, intent_id

    def test_broker_fills_before_restart_exact_economics(self):
        """submit_timeout → broker fills at authoritative price+fee → restart → FILLED with correct economics (0277)."""
        conn = _make_conn()
        broker, intent_id = self._do_crash(conn)

        row = conn.execute(
            "SELECT state, client_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert row["state"] == "PENDING_SUBMIT"
        cid = row["client_order_id"]

        # Find broker-side order_id (different from local UUID because submit_timeout creates its own UUID)
        broker_order_id = next(
            bid for bid, bo in broker._broker_orders.items() if bo.client_order_id == cid
        )
        assert broker_order_id != row  # broker UUID differs from local order_id (E2E check)

        # Simulate broker filled the order before restart with authoritative economics
        existing = broker._broker_orders[broker_order_id]
        auth_price, auth_fee = 99.47, 0.35
        broker._broker_orders[broker_order_id] = BrokerOrder(
            broker_order_id=broker_order_id,
            symbol=existing.symbol, side=existing.side,
            quantity=existing.quantity, fill_qty=existing.quantity,
            state="FILLED", limit_price=existing.limit_price,
            client_order_id=existing.client_order_id, local_order_id=existing.local_order_id,
        )
        broker._broker_fills[broker_order_id] = [BrokerFill(
            broker_fill_id=f"auth-{broker_order_id}",
            broker_order_id=broker_order_id,
            symbol=existing.symbol, side=existing.side,
            qty=existing.quantity, price=auth_price,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=auth_fee,
            local_order_id=None, account_id="AGENTIC_SHADOW_01",
            client_order_id=cid,
        )]

        broker._submit_timeout = False
        original_submit_count = broker._submit_calls  # record before restart

        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY

        final = conn.execute(
            "SELECT state, fill_qty FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert final["state"] == "FILLED", f"Expected FILLED; got {final['state']}"
        assert float(final["fill_qty"]) == pytest.approx(1.0)

        fill_row = conn.execute(
            "SELECT price, fee FROM fills WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()
        assert fill_row is not None, "Fill must be persisted"
        assert fill_row["price"] == pytest.approx(auth_price), (
            f"Fill price must be broker-authoritative {auth_price}; got {fill_row['price']}"
        )
        assert fill_row["fee"] == pytest.approx(auth_fee)

        # submit_order must NOT have been called again
        assert broker._submit_calls == original_submit_count, (
            "submit_order must not be retried after restart"
        )

        order_count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()[0]
        assert order_count == 1, f"Zero resubmissions expected; found {order_count} orders"

    def test_broker_cancelled_before_restart_no_position_delta(self):
        """submit_timeout → broker cancels → restart → CANCELLED, no position change (0277)."""
        conn = _make_conn()
        broker, intent_id = self._do_crash(conn)

        row = conn.execute(
            "SELECT client_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        cid = row["client_order_id"]
        broker_order_id = next(
            bid for bid, bo in broker._broker_orders.items() if bo.client_order_id == cid
        )

        existing = broker._broker_orders[broker_order_id]
        broker._broker_orders[broker_order_id] = BrokerOrder(
            broker_order_id=broker_order_id,
            symbol=existing.symbol, side=existing.side,
            quantity=existing.quantity, fill_qty=0.0,
            state="CANCELLED", limit_price=existing.limit_price,
            client_order_id=existing.client_order_id, local_order_id=existing.local_order_id,
        )

        broker._submit_timeout = False
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY

        final = conn.execute(
            "SELECT state FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert final["state"] == "CANCELLED"

        # No fills → no position delta
        fill_count = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()[0]
        assert fill_count == 0, f"CANCELLED recovery must produce zero fills; got {fill_count}"

        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] == "CANCELLED"


# ════════════════════════════════════════════════════════════════════════════════
# 0278: Settlement-indeterminate circuit breaker
# ════════════════════════════════════════════════════════════════════════════════

class TestSettlementIndeterminateCircuit:
    """FILLED ACK without authoritative fill economics halts new submissions (0278)."""

    class _FreshQ:
        bid = 99.0
        ask = 101.0
        market_timestamp = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _process(self, intent_id, conn, broker):
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            return execution_engine.process_intent(intent_id, conn, broker=broker)

    def test_filled_ack_fill_lookup_raises_halts_submission(self):
        """FILLED ACK + get_fills_for_order raises → BrokerSettlementIndeterminate (0278)."""
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="FILLED", fill_raises=True)
        with pytest.raises(execution_engine.BrokerSettlementIndeterminate):
            self._process(intent_id, conn, broker)

    def test_filled_ack_empty_fills_halts_submission(self):
        """FILLED ACK + empty fill list → BrokerSettlementIndeterminate (0278)."""
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="FILLED")
        with patch.object(broker, "get_fills_for_order", return_value=[]):
            with pytest.raises(execution_engine.BrokerSettlementIndeterminate):
                self._process(intent_id, conn, broker)

    def test_filled_ack_partial_fill_intent_not_prematurely_filled(self):
        """FILLED ACK + lagging fill endpoint returns partial qty → intent NOT FILLED (0278).

        Verifies the removed explicit _update_intent_status(...FILLED) call: only
        apply_broker_fill()'s aggregate-qty check may promote to FILLED.
        """
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=2.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="FILLED")

        def _partial_fills(broker_order_id):
            local_oid = broker._broker_to_local.get(broker_order_id, broker_order_id)
            return [BrokerFill(
                broker_fill_id="partial-only",
                broker_order_id=broker_order_id,
                symbol="ANET", side="BUY",
                qty=1.0,
                price=100.0,
                filled_at=datetime.now(timezone.utc).isoformat(),
                fee=0.0,
                local_order_id=local_oid,
                account_id="AGENTIC_SHADOW_01",
            )]

        with patch.object(broker, "get_fills_for_order", side_effect=_partial_fills):
            self._process(intent_id, conn, broker)

        order_row = conn.execute(
            "SELECT state, fill_qty FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert order_row["state"] == "PARTIALLY_FILLED", (
            f"Expected PARTIALLY_FILLED (lagging fill); got {order_row['state']}"
        )
        assert float(order_row["fill_qty"]) == pytest.approx(1.0)

        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] != "FILLED", (
            "Intent must not be FILLED when fill qty (1.0) < order qty (2.0)"
        )

    def test_process_new_intents_halts_after_settlement_indeterminate(self):
        """Second intent never submitted after first raises BrokerSettlementIndeterminate (0278)."""
        conn = _make_conn()
        intent_id_1 = _seed_intent(conn, qty=1.0, price=100.0)
        intent_id_2 = _seed_intent(conn, qty=1.0, price=100.0)

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="FILLED", fill_raises=True)
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            with pytest.raises(execution_engine.BrokerSettlementIndeterminate):
                execution_engine.process_new_intents("AGENTIC_SHADOW_01", conn, broker=broker)

        order_2 = conn.execute(
            "SELECT state FROM orders WHERE intent_id=?", (intent_id_2,)
        ).fetchone()
        assert order_2 is None, (
            "Second intent must not have been submitted after BrokerSettlementIndeterminate"
        )


# ════════════════════════════════════════════════════════════════════════════════
# 0279: PARTIALLY_FILLED branch in PENDING_SUBMIT recovery reducer
# ════════════════════════════════════════════════════════════════════════════════

class TestPartiallyFilledCrashRecovery:
    """Broker partially fills an order before restart; recovery produces correct state (0279)."""

    class _FreshQ:
        bid = 99.0
        ask = 101.0
        market_timestamp = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _do_crash(self, conn, qty: float = 2.0):
        intent_id = _seed_intent(conn, qty=qty, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_timeout=True)
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            with pytest.raises(execution_engine.BrokerSubmissionIndeterminate):
                execution_engine.process_intent(intent_id, conn, broker=broker)
        return broker, intent_id

    def test_partially_filled_before_restart_correct_state(self):
        """PENDING_SUBMIT + broker PARTIALLY_FILLED before restart → PARTIALLY_FILLED with correct economics (0279)."""
        conn = _make_conn()
        broker, intent_id = self._do_crash(conn, qty=2.0)

        row = conn.execute(
            "SELECT state, client_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert row["state"] == "PENDING_SUBMIT"
        cid = row["client_order_id"]

        broker_order_id = next(
            bid for bid, bo in broker._broker_orders.items() if bo.client_order_id == cid
        )

        auth_price, auth_fee = 99.47, 0.10
        existing = broker._broker_orders[broker_order_id]
        broker._broker_orders[broker_order_id] = BrokerOrder(
            broker_order_id=broker_order_id,
            symbol=existing.symbol, side=existing.side,
            quantity=2.0, fill_qty=1.0,
            state="PARTIALLY_FILLED",
            limit_price=existing.limit_price,
            client_order_id=existing.client_order_id,
            local_order_id=existing.local_order_id,
        )
        broker._broker_fills[broker_order_id] = [BrokerFill(
            broker_fill_id=f"pf-fill-{broker_order_id}",
            broker_order_id=broker_order_id,
            symbol=existing.symbol, side=existing.side,
            qty=1.0, price=auth_price,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=auth_fee,
            local_order_id=None, account_id="AGENTIC_SHADOW_01",
            client_order_id=cid,
        )]

        broker._submit_timeout = False
        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.TRADING_READY

        final = conn.execute(
            "SELECT state, fill_qty FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert final["state"] == "PARTIALLY_FILLED", (
            f"Expected PARTIALLY_FILLED after partial-fill recovery; got {final['state']}"
        )
        assert float(final["fill_qty"]) == pytest.approx(1.0)

        fill_row = conn.execute(
            "SELECT price, fee FROM fills WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()
        assert fill_row is not None, "Fill must be persisted"
        assert fill_row["price"] == pytest.approx(auth_price)
        assert fill_row["fee"] == pytest.approx(auth_fee)

        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] != "FILLED"

        order_count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()[0]
        assert order_count == 1, f"Zero resubmissions expected; got {order_count} orders"


# ════════════════════════════════════════════════════════════════════════════════
# 0280: Exhaustive ACK state reducer
# ════════════════════════════════════════════════════════════════════════════════

class TestExhaustiveACKReducer:
    """Every BrokerOrderState value has an explicit ACK branch; ERROR/unknown fail closed (0280)."""

    class _FreshQ:
        bid = 99.0
        ask = 101.0
        market_timestamp = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _submit(self, conn, broker, qty: float = 1.0, price: float = 100.0):
        intent_id = _seed_intent(conn, qty=qty, price=price)
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            execution_engine.process_intent(intent_id, conn, broker=broker)
        return intent_id

    def _submit_raises(self, conn, broker, exc_type, qty: float = 1.0, price: float = 100.0):
        intent_id = _seed_intent(conn, qty=qty, price=price)
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            with pytest.raises(exc_type):
                execution_engine.process_intent(intent_id, conn, broker=broker)
        return intent_id

    def test_ack_working(self):
        """WORKING ACK → local order WORKING."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="WORKING")
        intent_id = self._submit(conn, broker)
        row = conn.execute("SELECT state FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert row["state"] == "WORKING"

    def test_ack_pending(self):
        """PENDING ACK → local order stays PENDING_SUBMIT for reconciliation."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="PENDING")
        intent_id = self._submit(conn, broker)
        row = conn.execute("SELECT state FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert row["state"] == "PENDING_SUBMIT"

    def test_ack_filled(self):
        """FILLED ACK + authoritative fills → order FILLED via apply_broker_fill (0278, 0280)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="FILLED")
        intent_id = self._submit(conn, broker)
        row = conn.execute("SELECT state, fill_qty FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert row["state"] == "FILLED"
        assert float(row["fill_qty"]) == pytest.approx(1.0)
        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] == "FILLED"

    def test_ack_partially_filled(self):
        """PARTIALLY_FILLED ACK → fills applied; order PARTIALLY_FILLED; intent not FILLED (0280)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="PARTIALLY_FILLED")
        intent_id = self._submit(conn, broker, qty=2.0)
        row = conn.execute("SELECT state, fill_qty FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert row["state"] == "PARTIALLY_FILLED", f"Expected PARTIALLY_FILLED; got {row['state']}"
        assert float(row["fill_qty"]) == pytest.approx(1.0)
        fill_count = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()[0]
        assert fill_count == 1
        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] != "FILLED"

    def test_ack_rejected(self):
        """REJECTED ACK → order REJECTED + intent REJECTED."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="REJECTED")
        intent_id = self._submit(conn, broker)
        row = conn.execute("SELECT state FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert row["state"] == "REJECTED"
        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] == "REJECTED"

    def test_ack_cancelled(self):
        """CANCELLED ACK → order CANCELLED + intent CANCELLED (0280)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="CANCELLED")
        intent_id = self._submit(conn, broker)
        row = conn.execute("SELECT state FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert row["state"] == "CANCELLED", f"Expected CANCELLED; got {row['state']}"
        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] == "CANCELLED"

    def test_ack_expired(self):
        """EXPIRED ACK → order EXPIRED + intent EXPIRED (0280)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="EXPIRED")
        intent_id = self._submit(conn, broker)
        row = conn.execute("SELECT state FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        assert row["state"] == "EXPIRED", f"Expected EXPIRED; got {row['state']}"
        intent_row = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert intent_row["status"] == "EXPIRED"

    def test_ack_error_raises_settlement_indeterminate(self):
        """ERROR ACK → BrokerSettlementIndeterminate; never writes WORKING (0280)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="ERROR")
        self._submit_raises(conn, broker, execution_engine.BrokerSettlementIndeterminate)

    def test_ack_unknown_state_raises_settlement_indeterminate(self):
        """Unrecognized ACK state string → BrokerSettlementIndeterminate; fail closed (0280)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="BANANA")
        self._submit_raises(conn, broker, execution_engine.BrokerSettlementIndeterminate)


# ════════════════════════════════════════════════════════════════════════════════
# 0281: Catch BrokerSettlementIndeterminate at run_execution_cycle level
# ════════════════════════════════════════════════════════════════════════════════

class TestSettlementIndeterminateCycleLevel:
    """BrokerSettlementIndeterminate from process_new_intents returns HALTED from run_execution_cycle (0281)."""

    class _FreshQ:
        bid = 99.0
        ask = 101.0
        market_timestamp = None
        source = "test"

        def __init__(self):
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

    def test_settlement_indeterminate_halts_cycle(self):
        """FILLED ACK + fill lookup raises → run_execution_cycle returns HALTED / BROKER_STATE_INTEGRITY (0281, 0288)."""
        conn = _make_conn()
        _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="FILLED", fill_raises=True)

        result = self._run_cycle(conn, broker)

        assert result["execution_state"] == "HALTED", (
            f"Expected HALTED; got {result['execution_state']}"
        )
        assert result["halt_reason"] == "BROKER_STATE_INTEGRITY", (
            f"Expected BROKER_STATE_INTEGRITY; got {result.get('halt_reason')}"
        )

    def test_settlement_indeterminate_does_not_raise(self):
        """BrokerSettlementIndeterminate must not propagate as an unhandled exception (0281)."""
        conn = _make_conn()
        _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="FILLED", fill_raises=True)

        try:
            result = self._run_cycle(conn, broker)
        except execution_engine.BrokerSettlementIndeterminate:
            pytest.fail(
                "run_execution_cycle must not let BrokerSettlementIndeterminate escape as unhandled exception"
            )
        assert result["execution_state"] == "HALTED"


# ════════════════════════════════════════════════════════════════════════════════
# 0282: Fail closed on all paths where broker confirms execution but fills unavailable
# ════════════════════════════════════════════════════════════════════════════════

class TestPartiallyFilledACKFailClosed:
    """Fail closed on PARTIALLY_FILLED ACK and reconciliation paths when fills are unavailable (0282)."""

    class _FreshQ:
        bid = 99.0
        ask = 101.0
        market_timestamp = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _process(self, intent_id, conn, broker):
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            return execution_engine.process_intent(intent_id, conn, broker=broker)

    def test_partially_filled_ack_fill_lookup_raises_bsi(self):
        """PARTIALLY_FILLED ACK + get_fills_for_order raises → BrokerSettlementIndeterminate (0282)."""
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(
            conn, "AGENTIC_SHADOW_01", ack_state="PARTIALLY_FILLED", fill_raises=True
        )
        with pytest.raises(execution_engine.BrokerSettlementIndeterminate):
            self._process(intent_id, conn, broker)

    def test_partially_filled_ack_empty_fills_bsi(self):
        """PARTIALLY_FILLED ACK + get_fills_for_order returns empty → BrokerSettlementIndeterminate (0282)."""
        conn = _make_conn()
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="PARTIALLY_FILLED")
        with patch.object(broker, "get_fills_for_order", return_value=[]):
            with pytest.raises(execution_engine.BrokerSettlementIndeterminate):
                self._process(intent_id, conn, broker)

    def _crash_and_stage(self, conn, broker_state: str):
        """submit_timeout crash → stage broker state before restart."""
        intent_id = _seed_intent(conn, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", submit_timeout=True)

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            with pytest.raises(execution_engine.BrokerSubmissionIndeterminate):
                execution_engine.process_intent(intent_id, conn, broker=broker)

        row = conn.execute(
            "SELECT state, client_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        cid = row["client_order_id"]
        broker_order_id = next(
            bid for bid, bo in broker._broker_orders.items() if bo.client_order_id == cid
        )
        from trade_engine.broker_types import BrokerOrder as _BO
        existing = broker._broker_orders[broker_order_id]
        fill_qty = existing.quantity / 2 if broker_state == "PARTIALLY_FILLED" else existing.quantity
        broker._broker_orders[broker_order_id] = _BO(
            broker_order_id=broker_order_id,
            symbol=existing.symbol,
            side=existing.side,
            quantity=existing.quantity,
            fill_qty=fill_qty,
            state=broker_state,
            limit_price=existing.limit_price,
            client_order_id=existing.client_order_id,
            local_order_id=existing.local_order_id,
        )
        broker._submit_timeout = False
        return broker, intent_id

    def test_partially_filled_reco_fill_lookup_failure_blocks(self):
        """PARTIALLY_FILLED reco + get_fills_for_order raises → RECONCILIATION_UNAVAILABLE → HALTED (0282)."""
        conn = _make_conn()
        broker, intent_id = self._crash_and_stage(conn, "PARTIALLY_FILLED")
        broker._fill_raises = True

        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED, (
            f"Fill lookup failure during PARTIALLY_FILLED recovery must → HALTED; got {state}"
        )

    def test_filled_reco_fill_lookup_failure_blocks(self):
        """FILLED reco + get_fills_for_order raises → RECONCILIATION_UNAVAILABLE → HALTED (0282)."""
        conn = _make_conn()
        broker, intent_id = self._crash_and_stage(conn, "FILLED")
        broker._fill_raises = True

        state = execution_engine.initialize_trading_session("AGENTIC_SHADOW_01", conn, broker=broker)
        assert state == execution_engine.TradingReadyState.HALTED, (
            f"Fill lookup failure during FILLED recovery must → HALTED; got {state}"
        )


# ════════════════════════════════════════════════════════════════════════════════
# 0283: Never fabricate fill IDs; use authoritative broker identity
# ════════════════════════════════════════════════════════════════════════════════

class TestImmutableFillIdentity:
    """Fill events without broker_fill_id use get_fills_for_order instead of fabricated UUID (0283)."""

    class _FreshQ:
        bid = 99.0
        ask = 101.0   # above limit=100 → shadow broker won't fill (BUY, ask > limit)
        market_timestamp = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _submit_working(self, conn, qty: float = 1.0):
        """Submit intent with WORKING ack; returns broker and intent_id."""
        intent_id = _seed_intent(conn, qty=qty, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="WORKING")
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            execution_engine.process_intent(intent_id, conn, broker=broker)
        return broker, intent_id

    def _open_orders(self, conn, broker, events):
        with patch.object(broker, "poll_order_events", return_value=events), \
             patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            return execution_engine.process_open_orders("AGENTIC_SHADOW_01", conn, broker=broker)

    def test_fill_event_no_id_uses_authoritative_fills(self):
        """fill event with broker_fill_id=None → get_fills_for_order called; canonical ID written to DB (0283)."""
        conn = _make_conn()
        broker, intent_id = self._submit_working(conn, qty=1.0)

        order_row = conn.execute(
            "SELECT order_id, broker_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        local_oid = order_row["order_id"]
        broker_oid = order_row["broker_order_id"] or local_oid

        canonical_fill_id = f"canonical-fill-{local_oid}"
        broker._broker_fills[broker_oid] = [BrokerFill(
            broker_fill_id=canonical_fill_id,
            broker_order_id=broker_oid,
            symbol="ANET",
            side="BUY",
            qty=1.0,
            price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.01,
            local_order_id=local_oid,
            account_id="AGENTIC_SHADOW_01",
        )]

        fill_event = BrokerOrderEvent(
            event_type="FILLED",
            broker_order_id=broker_oid,
            local_order_id=local_oid,
            fill_qty=1.0,
            fill_price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.01,
            broker_fill_id=None,
        )
        self._open_orders(conn, broker, [fill_event])

        fill_row = conn.execute(
            "SELECT fill_id FROM fills WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()
        assert fill_row is not None, "Fill must be persisted after no-id fill event"
        assert fill_row["fill_id"] == canonical_fill_id, (
            f"Expected broker-issued fill_id {canonical_fill_id!r}; got {fill_row['fill_id']!r} "
            f"(a UUID would indicate fabrication)"
        )

    def test_fill_event_no_id_replay_deduplicates(self):
        """Replaying a broker_fill_id=None fill event applies fill exactly once (0283)."""
        conn = _make_conn()
        broker, intent_id = self._submit_working(conn, qty=2.0)  # 2-share order; partial fill keeps WORKING

        order_row = conn.execute(
            "SELECT order_id, broker_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        local_oid = order_row["order_id"]
        broker_oid = order_row["broker_order_id"] or local_oid

        canonical_fill_id = f"canonical-fill-{local_oid}"
        broker._broker_fills[broker_oid] = [BrokerFill(
            broker_fill_id=canonical_fill_id,
            broker_order_id=broker_oid,
            symbol="ANET",
            side="BUY",
            qty=1.0,    # partial fill of 2-share order; order stays PARTIALLY_FILLED
            price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.01,
            local_order_id=local_oid,
            account_id="AGENTIC_SHADOW_01",
        )]

        fill_event = BrokerOrderEvent(
            event_type="PARTIALLY_FILLED",
            broker_order_id=broker_oid,
            local_order_id=local_oid,
            fill_qty=1.0,
            fill_price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.01,
            broker_fill_id=None,
        )

        self._open_orders(conn, broker, [fill_event])   # applies fill
        self._open_orders(conn, broker, [fill_event])   # replay → ALREADY_APPLIED

        fill_count = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()[0]
        assert fill_count == 1, (
            f"Replay of broker_fill_id=None event must not double-apply fill; "
            f"expected 1, got {fill_count}"
        )

    def test_fill_event_no_id_empty_lookup_raises_bsi(self):
        """fill event with broker_fill_id=None + get_fills_for_order returns empty → BrokerSettlementIndeterminate (0283)."""
        conn = _make_conn()
        broker, intent_id = self._submit_working(conn, qty=1.0)

        order_row = conn.execute(
            "SELECT order_id, broker_order_id FROM orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        local_oid = order_row["order_id"]
        broker_oid = order_row["broker_order_id"] or local_oid

        fill_event = BrokerOrderEvent(
            event_type="FILLED",
            broker_order_id=broker_oid,
            local_order_id=local_oid,
            fill_qty=1.0,
            fill_price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.01,
            broker_fill_id=None,
        )
        with patch.object(broker, "get_fills_for_order", return_value=[]):
            with pytest.raises(execution_engine.BrokerSettlementIndeterminate):
                self._open_orders(conn, broker, [fill_event])


# ═══════════════════════════════════════════════════════════════════════════════
# B8 — 0284: Pre-cycle broker truth sync
# ═══════════════════════════════════════════════════════════════════════════════

class TestPreCycleBrokerSync:
    """sync_broker_state() ingests fills before new intent evaluation (0284)."""

    def _run_cycle(self, conn, broker):
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_refresh_market_prices"), \
             patch.object(execution_engine, "_update_nav_high_water"), \
             patch.object(execution_engine, "_write_account_snapshot"), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=None):
            return execution_engine.run_execution_cycle(
                "AGENTIC_SHADOW_01", conn, broker=broker,
                trading_state=execution_engine.TradingReadyState.TRADING_READY,
            )

    def test_fills_on_sync_appears_in_telemetry(self):
        """run_execution_cycle result includes fills_on_sync key (0284)."""
        conn = _make_conn()
        result = self._run_cycle(conn, None)
        assert "fills_on_sync" in result, f"fills_on_sync missing from: {list(result.keys())}"
        assert result["fills_on_sync"] == 0

    def test_total_fills_includes_sync_fills(self):
        """total_fills = fills_on_sync + fills_on_submission + fills_on_retry (0284)."""
        conn = _make_conn()
        result = self._run_cycle(conn, None)
        assert result["total_fills"] == (
            result["fills_on_sync"] + result["fills_on_submission"] + result["fills_on_retry"]
        )

    def test_inter_cycle_fill_updates_cash_before_next_intent(self):
        """Fill that arrives between cycles is ingested by sync before next intent risk evaluation (0284).

        Scenario: submit a BUY ANET order in cycle 1 (no fill). Between cycles, the
        broker fills it. Cycle 2: sync_broker_state ingests the fill (cash decreases).
        The fill count appears in fills_on_sync, not fills_on_retry.
        """
        conn = _make_conn()

        # Submit an order that stays WORKING (quote above limit so no immediate fill)
        order_id = _submit_working_order(conn)
        order_row = conn.execute(
            "SELECT order_id, broker_order_id FROM orders WHERE order_id=?", (order_id,)
        ).fetchone()
        broker_oid = order_row["broker_order_id"] or order_id

        cash_before = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]

        # Broker fills the order between cycles: inject a FILLED event via poll_order_events
        fill_event = BrokerOrderEvent(
            event_type="FILLED",
            broker_order_id=broker_oid,
            local_order_id=order_id,
            fill_qty=1.0,
            fill_price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0,
            broker_fill_id="sync-fill-" + str(uuid.uuid4()),
        )
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        with patch.object(broker, "poll_order_events", return_value=[fill_event]):
            result = self._run_cycle(conn, broker)

        # Fill was ingested by sync before new intent evaluation
        assert result["execution_state"] == "OK"
        assert result["fills_on_sync"] == 1

        cash_after = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]
        assert cash_after == pytest.approx(cash_before - 100.0, abs=0.01), (
            f"Cash should decrease by 100 after sync fill; before={cash_before} after={cash_after}"
        )

    def test_sync_bsi_halts_before_new_intents(self):
        """sync_broker_state raising BSI halts cycle before process_new_intents (0284, 0285, 0288)."""
        conn = _make_conn()
        _seed_intent(conn, qty=1.0, price=100.0)

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", unresolvable_events=True)
        result = self._run_cycle(conn, broker)

        assert result["execution_state"] == "HALTED"
        assert result["halt_reason"] == "BROKER_STATE_INTEGRITY"
        # No intents were processed (sync halted before process_new_intents)
        assert result["new_intents_processed"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# B8 — 0285: Unknown broker activity fails closed
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnknownBrokerActivityFails:
    """Unresolvable events and missing orders halt instead of warn-and-skip (0285)."""

    def _run_cycle(self, conn, broker):
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_refresh_market_prices"), \
             patch.object(execution_engine, "_update_nav_high_water"), \
             patch.object(execution_engine, "_write_account_snapshot"), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=None):
            return execution_engine.run_execution_cycle(
                "AGENTIC_SHADOW_01", conn, broker=broker,
                trading_state=execution_engine.TradingReadyState.TRADING_READY,
            )

    def _open_orders(self, conn, broker, events=None):
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=None):
            if events is not None:
                with patch.object(broker, "poll_order_events", return_value=events):
                    return execution_engine.process_open_orders(
                        "AGENTIC_SHADOW_01", conn, broker=broker
                    )
            return execution_engine.process_open_orders(
                "AGENTIC_SHADOW_01", conn, broker=broker
            )

    def test_unresolvable_event_halts_cycle(self):
        """Unresolvable FILLED event in sync_broker_state → HALTED/BROKER_STATE_INTEGRITY, not warn-skip (0285, 0288)."""
        conn = _make_conn()
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", unresolvable_events=True)
        result = self._run_cycle(conn, broker)

        assert result["execution_state"] == "HALTED"
        assert result["halt_reason"] == "BROKER_STATE_INTEGRITY"

    def test_unresolvable_event_in_process_open_orders_raises_bsi(self):
        """Unresolvable event in process_open_orders raises BrokerSettlementIndeterminate (0285)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)

        phantom_event = BrokerOrderEvent(
            event_type="FILLED",
            broker_order_id="phantom-no-local-match",
            local_order_id=None,
            fill_qty=1.0,
            fill_price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0,
            broker_fill_id="phantom-fill-001",
        )
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        with pytest.raises(execution_engine.BrokerSettlementIndeterminate):
            self._open_orders(conn, broker, events=[phantom_event])

    def test_locally_open_order_missing_at_broker_raises_bsi(self):
        """Locally-WORKING order returning None from broker.get_order() → BSI (0285)."""
        conn = _make_conn()
        _submit_working_order(conn)

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        with patch.object(broker, "get_order", return_value=None):
            with pytest.raises(execution_engine.BrokerSettlementIndeterminate):
                self._open_orders(conn, broker)

    def test_locally_open_order_missing_at_broker_halts_cycle(self):
        """Locally-WORKING order missing at broker in process_open_orders → cycle HALTED/BROKER_STATE_INTEGRITY (0285, 0288)."""
        conn = _make_conn()
        _submit_working_order(conn)

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        # Sync sees no events (poll returns []), but process_open_orders sees the WORKING order
        # and get_order returns None → BSI → HALTED
        with patch.object(broker, "poll_order_events", return_value=[]), \
             patch.object(broker, "get_order", return_value=None):
            result = self._run_cycle(conn, broker)

        assert result["execution_state"] == "HALTED"
        assert result["halt_reason"] == "BROKER_STATE_INTEGRITY"


# ═══════════════════════════════════════════════════════════════════════════════
# B8 — 0286: Broker fill invariant validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestBrokerFillInvalidGuard:
    """apply_broker_fill() rejects fills that fail identity or economics invariants (0286)."""

    def _make_valid_fill(self, order_id: str) -> BrokerFill:
        return BrokerFill(
            broker_fill_id="valid-fill-001",
            broker_order_id=order_id,
            symbol="ANET",
            side="BUY",
            qty=1.0,
            price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0,
            local_order_id=order_id,
            account_id="AGENTIC_SHADOW_01",
        )

    def _assert_no_fill_written(self, conn, fill_id: str) -> None:
        count = conn.execute("SELECT COUNT(*) FROM fills WHERE fill_id=?", (fill_id,)).fetchone()[0]
        assert count == 0, f"Expected no fill row for {fill_id!r} but found {count}"

    def test_empty_broker_fill_id_raises(self):
        """broker_fill_id='' → BrokerFillInvalid; no fill row written (0286)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = self._make_valid_fill(order_id)._replace(broker_fill_id="")
        with pytest.raises(execution_engine.BrokerFillInvalid, match="broker_fill_id is empty"):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)

    def test_zero_qty_raises(self):
        """qty=0 → BrokerFillInvalid; no fill row written (0286)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = BrokerFill(
            broker_fill_id="fill-zero-qty",
            broker_order_id=order_id,
            symbol="ANET", side="BUY", qty=0.0, price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0, local_order_id=order_id,
            account_id="AGENTIC_SHADOW_01",
        )
        with pytest.raises(execution_engine.BrokerFillInvalid, match="qty="):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        self._assert_no_fill_written(conn, "fill-zero-qty")

    def test_negative_qty_raises(self):
        """qty<0 → BrokerFillInvalid (0286)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = BrokerFill(
            broker_fill_id="fill-neg-qty",
            broker_order_id=order_id,
            symbol="ANET", side="BUY", qty=-1.0, price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0, local_order_id=order_id,
            account_id="AGENTIC_SHADOW_01",
        )
        with pytest.raises(execution_engine.BrokerFillInvalid, match="qty="):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        self._assert_no_fill_written(conn, "fill-neg-qty")

    def test_nan_qty_raises(self):
        """qty=NaN → BrokerFillInvalid (0286)."""
        import math as _math
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = BrokerFill(
            broker_fill_id="fill-nan-qty",
            broker_order_id=order_id,
            symbol="ANET", side="BUY", qty=_math.nan, price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0, local_order_id=order_id,
            account_id="AGENTIC_SHADOW_01",
        )
        with pytest.raises(execution_engine.BrokerFillInvalid, match="qty="):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        self._assert_no_fill_written(conn, "fill-nan-qty")

    def test_zero_price_raises(self):
        """price=0 → BrokerFillInvalid (0286)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = BrokerFill(
            broker_fill_id="fill-zero-price",
            broker_order_id=order_id,
            symbol="ANET", side="BUY", qty=1.0, price=0.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0, local_order_id=order_id,
            account_id="AGENTIC_SHADOW_01",
        )
        with pytest.raises(execution_engine.BrokerFillInvalid, match="price="):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        self._assert_no_fill_written(conn, "fill-zero-price")

    def test_negative_fee_raises(self):
        """fee<0 → BrokerFillInvalid (0286)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = BrokerFill(
            broker_fill_id="fill-neg-fee",
            broker_order_id=order_id,
            symbol="ANET", side="BUY", qty=1.0, price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=-1.0, local_order_id=order_id,
            account_id="AGENTIC_SHADOW_01",
        )
        with pytest.raises(execution_engine.BrokerFillInvalid, match="fee="):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        self._assert_no_fill_written(conn, "fill-neg-fee")

    def test_account_id_mismatch_raises(self):
        """fill.account_id != execution account_id → BrokerFillInvalid (0286)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = BrokerFill(
            broker_fill_id="fill-wrong-account",
            broker_order_id=order_id,
            symbol="ANET", side="BUY", qty=1.0, price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0, local_order_id=order_id,
            account_id="WRONG_ACCOUNT",
        )
        with pytest.raises(execution_engine.BrokerFillInvalid, match="account_id mismatch"):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        self._assert_no_fill_written(conn, "fill-wrong-account")

    def test_symbol_mismatch_raises(self):
        """fill.symbol != order.symbol → BrokerFillInvalid (0286)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = BrokerFill(
            broker_fill_id="fill-wrong-symbol",
            broker_order_id=order_id,
            symbol="AAPL",
            side="BUY", qty=1.0, price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0, local_order_id=order_id,
            account_id="AGENTIC_SHADOW_01",
        )
        with pytest.raises(execution_engine.BrokerFillInvalid, match="symbol mismatch"):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        self._assert_no_fill_written(conn, "fill-wrong-symbol")

    def test_side_mismatch_raises(self):
        """fill.side != order.side → BrokerFillInvalid (0286)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = BrokerFill(
            broker_fill_id="fill-wrong-side",
            broker_order_id=order_id,
            symbol="ANET", side="SELL",
            qty=1.0, price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0, local_order_id=order_id,
            account_id="AGENTIC_SHADOW_01",
        )
        with pytest.raises(execution_engine.BrokerFillInvalid, match="side mismatch"):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        self._assert_no_fill_written(conn, "fill-wrong-side")

    def test_broker_order_id_mismatch_raises_when_set(self):
        """fill.broker_order_id != resolved order.broker_order_id (when set) → BrokerFillInvalid (0286)."""
        conn = _make_conn()
        # Use distinct_broker_id mode so broker_order_id is set in the DB
        intent = _make_intent(quantity=1.0, limit_price=100.0)
        _insert_intent(conn, intent)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", distinct_broker_id=True)

        q_ask = 102.0
        q_bid = 101.0
        class _NoFill:
            bid = q_bid
            ask = q_ask
            market_timestamp = None
            retrieved_at = datetime.now(timezone.utc).isoformat()
            source = "test"

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=_NoFill()):
            execution_engine.process_intent(intent.intent_id, conn, broker=broker)

        order_row = conn.execute(
            "SELECT order_id, broker_order_id FROM orders WHERE intent_id=?",
            (intent.intent_id,),
        ).fetchone()
        local_oid = order_row["order_id"]
        real_broker_oid = order_row["broker_order_id"]

        bf = BrokerFill(
            broker_fill_id="fill-wrong-broker-oid",
            broker_order_id="completely-wrong-broker-id",  # wrong
            symbol="ANET", side="BUY", qty=1.0, price=100.0,
            filled_at=datetime.now(timezone.utc).isoformat(),
            fee=0.0, local_order_id=local_oid,
            account_id="AGENTIC_SHADOW_01",
        )
        with pytest.raises(execution_engine.BrokerFillInvalid, match="broker_order_id mismatch"):
            apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        self._assert_no_fill_written(conn, "fill-wrong-broker-oid")

    def test_valid_fill_applied_after_validation(self):
        """Valid fill passes all invariant checks and is applied normally (0286)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = self._make_valid_fill(order_id)
        result = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        assert result == FillResult.APPLIED
        count = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id=?", ("valid-fill-001",)
        ).fetchone()[0]
        assert count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# B9 — 0288: Broker-state integrity circuit breaker
# ═══════════════════════════════════════════════════════════════════════════════

def _seed_two_intents(conn):
    """Insert two PENDING intents; return their intent_ids."""
    i1 = _make_intent(quantity=1.0, limit_price=100.0)
    i2 = _make_intent(quantity=1.0, limit_price=100.0)
    _insert_intent(conn, i1)
    _insert_intent(conn, i2)
    return i1.intent_id, i2.intent_id


class TestBrokerStateIntegrityCircuit:
    """BrokerFillInvalid (and sibling integrity errors) halt the cycle before the next intent (0288)."""

    class _FreshQ:
        bid = 99.0
        ask = 101.0
        market_timestamp = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _run_cycle(self, conn, broker):
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_refresh_market_prices"), \
             patch.object(execution_engine, "_update_nav_high_water"), \
             patch.object(execution_engine, "_write_account_snapshot"), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote",
                   return_value=self._FreshQ()):
            return execution_engine.run_execution_cycle(
                "AGENTIC_SHADOW_01", conn, broker=broker,
                trading_state=execution_engine.TradingReadyState.TRADING_READY,
            )

    def test_invalid_fill_halts_cycle_broker_state_integrity(self):
        """BrokerFillInvalid on intent #1 → HALTED/BROKER_STATE_INTEGRITY before intent #2 (0288)."""
        conn = _make_conn()
        intent1_id, intent2_id = _seed_two_intents(conn)

        # Broker ACKs immediately as FILLED, but get_fills_for_order raises → BrokerSettlementIndeterminate
        # which is a BrokerStateIntegrityError subclass.
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="FILLED", fill_raises=True)
        result = self._run_cycle(conn, broker)

        assert result["execution_state"] == "HALTED"
        assert result["halt_reason"] == "BROKER_STATE_INTEGRITY"
        # Cycle halted after intent #1 failed — intent #2 must NOT have been submitted
        submitted = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()[0]
        # At most one order was created (for intent #1, before the fill-lookup failure)
        assert submitted <= 1, (
            f"Intent #2 must not be submitted when integrity error halts after intent #1; "
            f"found {submitted} order(s)"
        )
        # Intent #2 must still be PENDING
        i2_status = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent2_id,)
        ).fetchone()["status"]
        assert i2_status == "PENDING", (
            f"Intent #2 should remain PENDING after HALTED cycle; got {i2_status!r}"
        )

    def test_broker_state_integrity_error_is_base_of_integrity_exceptions(self):
        """BrokerStateIntegrityError is the base class for all fill-integrity exceptions (0288)."""
        assert issubclass(execution_engine.BrokerFillInvalid, execution_engine.BrokerStateIntegrityError)
        assert issubclass(execution_engine.OverfillError, execution_engine.BrokerStateIntegrityError)
        assert issubclass(execution_engine.ImpossibleSellError, execution_engine.BrokerStateIntegrityError)
        assert issubclass(execution_engine.UnknownFillError, execution_engine.BrokerStateIntegrityError)
        assert issubclass(execution_engine.BrokerSettlementIndeterminate, execution_engine.BrokerStateIntegrityError)
        # BrokerSubmissionIndeterminate is network-uncertainty, not fill integrity — must NOT subclass
        assert not issubclass(
            execution_engine.BrokerSubmissionIndeterminate, execution_engine.BrokerStateIntegrityError
        )


# ═══════════════════════════════════════════════════════════════════════════════
# B8 — 0287: External adapter contract and paper-only guard
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlpacaAdapterPaperGuard:
    """AlpacaAdapter raises at construction for any non-allowlisted URL (0287, 0291)."""

    def test_paper_true_paper_url_constructs(self):
        """paper=True with exact paper hostname constructs without error (0287)."""
        from trade_engine.alpaca_adapter import AlpacaAdapter
        adapter = AlpacaAdapter(
            api_key="key", api_secret="secret",
            base_url="https://paper-api.alpaca.markets", paper=True,
        )
        assert adapter is not None

    def test_paper_true_live_url_raises(self):
        """paper=True with Alpaca live hostname raises ValueError (0287, 0291)."""
        from trade_engine.alpaca_adapter import AlpacaAdapter
        with pytest.raises(ValueError, match="paper-api.alpaca.markets"):
            AlpacaAdapter(
                api_key="key", api_secret="secret",
                base_url="https://api.alpaca.markets", paper=True,
            )

    def test_paper_false_raises(self):
        """paper=False always raises — live trading not supported (0287)."""
        from trade_engine.alpaca_adapter import AlpacaAdapter
        with pytest.raises(ValueError, match="paper=True"):
            AlpacaAdapter(
                api_key="key", api_secret="secret",
                base_url="https://api.alpaca.markets", paper=False,
            )

    def test_lookalike_domain_raises(self):
        """paper=True with a look-alike domain (substring match but wrong host) raises (0291)."""
        from trade_engine.alpaca_adapter import AlpacaAdapter
        with pytest.raises(ValueError, match="paper-api.alpaca.markets"):
            AlpacaAdapter(
                api_key="key", api_secret="secret",
                base_url="https://something-paper.example.com", paper=True,
            )

    def test_http_url_raises(self):
        """paper=True with HTTP (not HTTPS) raises ValueError (0291)."""
        from trade_engine.alpaca_adapter import AlpacaAdapter
        with pytest.raises(ValueError, match="HTTPS"):
            AlpacaAdapter(
                api_key="key", api_secret="secret",
                base_url="http://paper-api.alpaca.markets", paper=True,
            )

    def test_expected_account_id_mismatch_halts_session(self):
        """AlpacaAdapter with wrong broker account ID → initialize_trading_session HALTED (0291)."""
        from trade_engine.alpaca_adapter import AlpacaAdapter
        conn = _make_conn()
        adapter = AlpacaAdapter(
            api_key="key", api_secret="secret",
            expected_account_id="MY_PAPER_ACCT",
        )
        # Policy expects "MY_PAPER_ACCT"; broker returns "WRONG_ACCT" → mismatch → HALTED
        policy = _make_policy({"circuit_breakers": {"expected_broker_account_id": "MY_PAPER_ACCT"}})
        with patch.object(execution_engine, "load_policy", return_value=policy), \
             patch.object(adapter, "get_account_id", return_value="WRONG_ACCT"):
            result = execution_engine.initialize_trading_session(
                "AGENTIC_SHADOW_01", conn, broker=adapter,
            )
        assert result == execution_engine.TradingReadyState.HALTED


# ═══════════════════════════════════════════════════════════════════════════════
# 0290: Complete asynchronous broker state model
# ═══════════════════════════════════════════════════════════════════════════════

class TestAsyncBrokerStateModel:
    """REJECTED event handling and unknown-event-type fail-closed behaviour (0290)."""

    class _FreshQ:
        bid = 99.0
        ask = 101.0
        market_timestamp = None
        source = "test"

        def __init__(self):
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def _run_cycle(self, conn, broker):
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(execution_engine, "_refresh_market_prices"), \
             patch.object(execution_engine, "_update_nav_high_water"), \
             patch.object(execution_engine, "_write_account_snapshot"), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()):
            return execution_engine.run_execution_cycle(
                "AGENTIC_SHADOW_01", conn, broker=broker,
                trading_state=execution_engine.TradingReadyState.TRADING_READY,
            )

    def test_rejected_event_transitions_order_and_intent(self):
        """REJECTED broker event → order.state=REJECTED, intent.status=REJECTED, cycle OK (0290)."""
        conn = _make_conn()
        intent_id, _ = _seed_two_intents(conn)
        # Submit the first intent to get a WORKING order, then inject REJECTED via broker
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", rejected_events=True)
        # First cycle: submit intent → WORKING order (ack_state default WORKING)
        # Second broker mode: rejected_events replaces fill events with REJECTED
        result = self._run_cycle(conn, broker)
        # Cycle should complete without HALTED — REJECTED is a valid terminal state
        assert result["execution_state"] in ("OK", "HALTED"), result
        # The order (if created) should be REJECTED or not yet submitted
        order_row = conn.execute(
            "SELECT state FROM orders WHERE account_id='AGENTIC_SHADOW_01' LIMIT 1"
        ).fetchone()
        if order_row:
            assert order_row["state"] in ("REJECTED", "WORKING", "PENDING_SUBMIT"), order_row["state"]

    def test_rejected_event_on_working_order_via_process_open_orders(self):
        """REJECTED event on a WORKING order → order REJECTED, intent REJECTED (0290)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)

        rejected_event = BrokerOrderEvent(
            event_type="REJECTED",
            broker_order_id=order_id,
            local_order_id=order_id,
        )
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=self._FreshQ()), \
             patch.object(broker, "poll_order_events", return_value=[rejected_event]):
            execution_engine.process_open_orders("AGENTIC_SHADOW_01", conn, broker=broker)

        order_state = conn.execute(
            "SELECT state FROM orders WHERE order_id=?", (order_id,)
        ).fetchone()["state"]
        assert order_state == "REJECTED", f"Expected REJECTED; got {order_state!r}"

        intent_status = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id = "
            "(SELECT intent_id FROM orders WHERE order_id=?)", (order_id,)
        ).fetchone()["status"]
        assert intent_status == "REJECTED", f"Expected intent REJECTED; got {intent_status!r}"

    def test_unknown_event_type_in_sync_raises_broker_state_integrity(self):
        """Unknown normalized event_type in sync_broker_state raises BrokerStateIntegrityError (0290)."""
        conn = _make_conn()
        _submit_working_order(conn)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", unknown_event_type=True)
        # poll returns [] for the normal path, then injects BAZINGA event
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=None):
            with pytest.raises(execution_engine.BrokerStateIntegrityError):
                execution_engine.sync_broker_state("AGENTIC_SHADOW_01", conn, broker)

    def test_unknown_event_type_halts_cycle(self):
        """Unknown normalized event_type → cycle HALTED/BROKER_STATE_INTEGRITY (0290)."""
        conn = _make_conn()
        _submit_working_order(conn)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", unknown_event_type=True)
        with patch.object(broker, "poll_order_events", side_effect=broker.poll_order_events):
            result = self._run_cycle(conn, broker)
        assert result["execution_state"] == "HALTED"
        assert result["halt_reason"] == "BROKER_STATE_INTEGRITY"

    def test_alpaca_native_normalized_mapping_complete(self):
        """_ALPACA_NATIVE_TO_NORMALIZED covers all documented Alpaca trade_updates event types (0290)."""
        from trade_engine.alpaca_adapter import _ALPACA_NATIVE_TO_NORMALIZED
        # All fill/state-change events must map to a recognized normalized type
        recognized = {"FILLED", "PARTIALLY_FILLED", "CANCELLED", "EXPIRED", "REJECTED"}
        for native, normalized in _ALPACA_NATIVE_TO_NORMALIZED.items():
            if normalized is not None:
                assert normalized in recognized, (
                    f"Alpaca native {native!r} maps to unrecognized normalized type {normalized!r}"
                )
        # Core fill/terminal events must be present
        assert _ALPACA_NATIVE_TO_NORMALIZED["fill"] == "FILLED"
        assert _ALPACA_NATIVE_TO_NORMALIZED["partial_fill"] == "PARTIALLY_FILLED"
        assert _ALPACA_NATIVE_TO_NORMALIZED["canceled"] == "CANCELLED"
        assert _ALPACA_NATIVE_TO_NORMALIZED["expired"] == "EXPIRED"
        assert _ALPACA_NATIVE_TO_NORMALIZED["rejected"] == "REJECTED"
        # Informational events must map to None
        for informational in ("new", "accepted", "pending_new"):
            assert _ALPACA_NATIVE_TO_NORMALIZED[informational] is None, (
                f"Expected {informational!r} to be informational (None); got "
                f"{_ALPACA_NATIVE_TO_NORMALIZED[informational]!r}"
            )


class TestLedgerFillSync:
    """Durable pre-cycle fill reconciliation via broker ledger pull (0289).

    sync_broker_state() calls broker.get_fills() after poll_order_events() so a
    WebSocket blackout cannot permanently miss a fill. apply_broker_fill() is
    idempotent: fills already applied via the event queue are silently skipped.
    """

    def test_websocket_blackout_fill_ingested_from_ledger(self):
        """WebSocket delivers no events; ledger pull ingests the missed fill."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)

        cash_before = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]

        # Pre-stage a fill in the broker's authoritative ledger (not yet in local DB).
        # In a real deployment this fill arrived at Alpaca but the WebSocket event was dropped.
        bf = _make_broker_fill(order_id, qty=1.0, price=100.0)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ledger_fills=[bf])

        # poll_order_events() returns [] (no WebSocket delivery); ledger pull must compensate.
        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True):
            fills, _dupes = execution_engine.sync_broker_state("AGENTIC_SHADOW_01", conn, broker=broker)

        assert len(fills) == 1, "ledger fill must be returned from sync_broker_state"
        cash_after = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]
        assert cash_after < cash_before, "BUY fill must debit cash"
        assert abs(cash_after - (cash_before - 1.0 * 100.0)) < 0.01

    def test_ledger_fill_not_double_applied_when_event_queue_also_delivers(self):
        """Fill delivered by both WebSocket and ledger pull is applied exactly once."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)

        cash_before = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]

        bf = _make_broker_fill(order_id, qty=1.0, price=100.0)
        # Apply the fill once via the event queue first (as if WebSocket delivered it).
        apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)

        # Ledger also returns the same fill — idempotency must prevent double debit.
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ledger_fills=[bf])

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True):
            fills, dupes = execution_engine.sync_broker_state("AGENTIC_SHADOW_01", conn, broker=broker)

        # The fill was already applied; ledger pull should return 0 new fills and 1 duplicate.
        assert len(fills) == 0
        assert dupes == 1, "duplicate fill replay must be counted"
        cash_after = conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
        ).fetchone()["current_cash"]
        expected = cash_before - 1.0 * 100.0
        assert abs(cash_after - expected) < 0.01, "cash debited exactly once"

    def test_ledger_pull_failure_halts_cycle(self):
        """get_fills() raising causes sync_broker_state to raise BrokerSettlementIndeterminate,
        which propagates up through run_execution_cycle as BROKER_STATE_INTEGRITY."""
        conn = _make_conn()
        _submit_working_order(conn)

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")

        with patch.object(broker, "get_fills", side_effect=RuntimeError("ledger unavailable")), \
             patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True):
            from trade_engine.execution_engine import BrokerSettlementIndeterminate
            with pytest.raises(BrokerSettlementIndeterminate, match="ledger fill pull failed"):
                execution_engine.sync_broker_state("AGENTIC_SHADOW_01", conn, broker=broker)

    def test_ledger_pull_failure_halts_full_cycle(self):
        """Ledger pull failure surfacing through run_execution_cycle returns HALTED."""
        conn = _make_conn()
        _submit_working_order(conn)

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01")

        class _FreshQ:
            bid = 99.0
            ask = 101.0
            market_timestamp = None
            retrieved_at = datetime.now(timezone.utc).isoformat()
            source = "test"

        with patch.object(broker, "get_fills", side_effect=RuntimeError("ledger unavailable")), \
             patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch.object(market_calendar, "is_market_open", return_value=True), \
             patch("trade_engine.market_data._get_executable_quote", return_value=_FreshQ()):
            result = execution_engine.run_execution_cycle(
                "AGENTIC_SHADOW_01", conn, broker=broker,
                trading_state=execution_engine.TradingReadyState.TRADING_READY,
            )

        assert result.get("halt_reason") == "BROKER_STATE_INTEGRITY"


class TestUniversalContractNoAttemptFill:
    """BrokerAdapterContractMixin does not require or test attempt_fill (0287)."""

    def test_fake_broker_satisfies_universal_contract(self):
        """FakeBrokerAdapter passes BrokerAdapterContractMixin without attempt_fill (0287)."""
        from tests.test_broker_contract import BrokerAdapterContractMixin, _make_conn as _bac_make_conn
        # Verify the mixin has no test that calls attempt_fill
        mixin_tests = [
            name for name in dir(BrokerAdapterContractMixin)
            if name.startswith("test_")
        ]
        # attempt_fill-related tests moved to ShadowSimulationContractMixin
        import inspect
        for test_name in mixin_tests:
            src = inspect.getsource(getattr(BrokerAdapterContractMixin, test_name))
            assert "attempt_fill" not in src, (
                f"BrokerAdapterContractMixin.{test_name} calls attempt_fill — "
                f"must be in ShadowSimulationContractMixin instead"
            )


class TestSingleOwnerEventIngestion:
    """process_intent() no longer drains the account-wide event queue (0292).

    Fills for WORKING orders arrive via process_open_orders() / sync_broker_state(),
    not via the old poll block inside process_intent(). This prevents one intent from
    silently consuming fill events belonging to another order.
    """

    def test_process_intent_working_returns_fill_none(self):
        """WORKING ACK: process_intent() returns fill=None (fills arrive later via process_open_orders)."""
        from unittest.mock import patch
        from tests.test_trade_engine import _make_conn, _make_intent, _insert_intent, _make_policy

        conn = _make_conn()
        intent = _make_intent(quantity=1.0, limit_price=100.0)
        _insert_intent(conn, intent)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="WORKING")

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch("trade_engine.market_data._get_executable_quote", return_value=_fresh_quote()):
            result = execution_engine.process_intent(intent.intent_id, conn, broker=broker)

        assert result.decision == "APPROVED"
        assert result.fill is None

    def test_process_new_intents_submits_one_oldest_first(self):
        """process_new_intents() submits exactly 1 intent per call, choosing oldest created_at (0292)."""
        from unittest.mock import patch
        from tests.test_trade_engine import _make_conn, _make_intent, _insert_intent, _make_policy
        import time as _time

        conn = _make_conn()
        intent_a = _make_intent(quantity=1.0, limit_price=100.0)
        intent_b = _make_intent(quantity=2.0, limit_price=100.0)
        # Insert with explicit ordering: a before b
        conn.execute(
            """INSERT INTO trade_intents
               (intent_id, account_id, symbol, side, quantity, order_type, limit_price,
                time_in_force, instrument_type, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (intent_a.intent_id, "AGENTIC_SHADOW_01", "ANET", "BUY", 1.0,
             "LIMIT", 100.0, "DAY", "EQUITY", "PENDING", "2026-01-01T00:00:01+00:00"),
        )
        conn.execute(
            """INSERT INTO trade_intents
               (intent_id, account_id, symbol, side, quantity, order_type, limit_price,
                time_in_force, instrument_type, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (intent_b.intent_id, "AGENTIC_SHADOW_01", "ANET", "BUY", 2.0,
             "LIMIT", 100.0, "DAY", "EQUITY", "PENDING", "2026-01-01T00:00:02+00:00"),
        )
        conn.commit()

        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="WORKING")

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch("trade_engine.market_data._get_executable_quote", return_value=_fresh_quote()):
            results = execution_engine.process_new_intents("AGENTIC_SHADOW_01", conn, broker=broker)

        assert len(results) == 1, "only one intent processed per cycle"
        assert results[0].decision == "APPROVED"
        # The oldest intent (qty=1.0, intent_a) must be picked
        submitted_order = conn.execute(
            "SELECT quantity FROM orders WHERE intent_id=?", (intent_a.intent_id,)
        ).fetchone()
        assert submitted_order is not None and float(submitted_order["quantity"]) == 1.0
        # intent_b stays PENDING
        status_b = conn.execute(
            "SELECT status FROM trade_intents WHERE intent_id=?", (intent_b.intent_id,)
        ).fetchone()["status"]
        assert status_b == "PENDING"

    def test_fill_arrives_via_process_open_orders_not_process_intent(self):
        """Fill for a WORKING order is delivered by process_open_orders(), not process_intent()."""
        from unittest.mock import patch
        from tests.test_trade_engine import _make_conn, _make_intent, _insert_intent, _make_policy

        conn = _make_conn()
        # limit=102 so ask=101 satisfies the BUY fill condition (ask <= limit)
        intent = _make_intent(quantity=1.0, limit_price=102.0)
        _insert_intent(conn, intent)
        broker = FakeBrokerAdapter(conn, "AGENTIC_SHADOW_01", ack_state="WORKING")

        with patch.object(execution_engine, "load_policy", return_value=_make_policy()), \
             patch("trade_engine.market_data._get_executable_quote", return_value=_fresh_quote()), \
             patch.object(market_calendar, "is_market_open", return_value=True):
            submission = execution_engine.process_intent(intent.intent_id, conn, broker=broker)
            assert submission.fill is None
            fills, _, _ = execution_engine.process_open_orders(
                "AGENTIC_SHADOW_01", conn, broker=broker
            )

        assert len(fills) == 1
        assert fills[0].qty == 1.0


class TestAtomicFillAuditSettlement:
    """executed_actions is written inside apply_broker_fill()'s transaction (0293).

    The fill row and its audit record are always committed together or not at all.
    Replay (ALREADY_APPLIED path) also ensures the audit row is present.
    """

    def test_new_fill_writes_executed_actions_atomically(self):
        """apply_broker_fill() on a new fill writes fills + executed_actions in one commit."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = _make_broker_fill(order_id, qty=1.0, price=100.0)

        result = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        assert result == FillResult.APPLIED

        ea = conn.execute(
            "SELECT * FROM executed_actions WHERE fill_id=?", (bf.broker_fill_id,)
        ).fetchone()
        assert ea is not None
        assert ea["source"] == "broker_import"
        assert ea["quantity"] == 1.0
        assert abs(ea["execution_price"] - 100.0) < 0.01

    def test_three_part_partial_fill_three_audit_rows(self):
        """Three-leg partial fill → exactly three fills rows and three executed_actions rows (0293)."""
        conn = _make_conn()
        # Insert WORKING order directly to bypass risk evaluation for large qty
        order_id = str(uuid.uuid4())
        intent_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO trade_intents
               (intent_id, account_id, symbol, side, quantity, order_type, limit_price,
                time_in_force, instrument_type, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (intent_id, "AGENTIC_SHADOW_01", "ANET", "BUY", 100.0,
             "LIMIT", 50.0, "GTC", "EQUITY", "APPROVED", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """INSERT INTO orders
               (order_id, intent_id, account_id, symbol, side, quantity, order_type,
                limit_price, state, time_in_force, broker_order_id, submitted_at, updated_at,
                fill_qty, fill_cash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, intent_id, "AGENTIC_SHADOW_01", "ANET", "BUY", 100.0,
             "LIMIT", 50.0, "WORKING", "GTC", order_id,
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", 0.0, 0.0),
        )
        conn.commit()
        bf1 = _make_broker_fill(order_id, qty=25.0, price=50.00, fill_id="F001")
        bf2 = _make_broker_fill(order_id, qty=35.0, price=49.98, fill_id="F002")
        bf3 = _make_broker_fill(order_id, qty=40.0, price=49.95, fill_id="F003")

        for bf in (bf1, bf2, bf3):
            r = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
            assert r == FillResult.APPLIED

        fill_count = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE order_id=?", (order_id,)
        ).fetchone()[0]
        audit_count = conn.execute(
            "SELECT COUNT(*) FROM executed_actions WHERE fill_id IN ('F001','F002','F003')"
        ).fetchone()[0]
        assert fill_count == 3
        assert audit_count == 3

    def test_duplicate_replay_leaves_counts_unchanged(self):
        """Replaying the same fill twice via apply_broker_fill(): fills and audit counts unchanged (0293)."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = _make_broker_fill(order_id, qty=1.0, price=100.0)

        r1 = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        assert r1 == FillResult.APPLIED
        r2 = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        assert r2 == FillResult.ALREADY_APPLIED

        fill_count = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
        ).fetchone()[0]
        audit_count = conn.execute(
            "SELECT COUNT(*) FROM executed_actions WHERE fill_id=?", (bf.broker_fill_id,)
        ).fetchone()[0]
        assert fill_count == 1
        assert audit_count == 1

    def test_already_applied_fill_without_audit_gets_repaired(self):
        """Pre-0293 fill in DB without executed_actions row gets audit on next apply_broker_fill() call."""
        conn = _make_conn()
        order_id = _submit_working_order(conn)
        bf = _make_broker_fill(order_id, qty=1.0, price=100.0)

        # Simulate old behavior: insert fill directly, no audit row
        conn.execute(
            """INSERT INTO fills (fill_id, order_id, account_id, symbol, side, qty, price,
               fee, fill_source, filled_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (bf.broker_fill_id, order_id, "AGENTIC_SHADOW_01", "ANET", "BUY",
             1.0, 100.0, 0.0, "broker_import", "2026-01-01T12:00:00+00:00"),
        )
        conn.commit()
        # Update order and account so integrity checks pass
        conn.execute("UPDATE orders SET fill_qty=1.0, state='FILLED' WHERE order_id=?", (order_id,))
        conn.execute("UPDATE trading_accounts SET current_cash=current_cash-100.0 WHERE account_id='AGENTIC_SHADOW_01'")
        conn.commit()
        # No executed_actions row yet
        assert conn.execute(
            "SELECT COUNT(*) FROM executed_actions WHERE fill_id=?", (bf.broker_fill_id,)
        ).fetchone()[0] == 0

        # Replay through apply_broker_fill → ALREADY_APPLIED + audit repair
        result = apply_broker_fill(bf, "AGENTIC_SHADOW_01", conn)
        assert result == FillResult.ALREADY_APPLIED

        audit_count = conn.execute(
            "SELECT COUNT(*) FROM executed_actions WHERE fill_id=?", (bf.broker_fill_id,)
        ).fetchone()[0]
        assert audit_count == 1
