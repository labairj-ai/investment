"""Unit tests for AlpacaAdapter — all HTTP mocked, no live network calls (0294, 0295).

Tests cover:
  - Construction guards (paper flag, URL hostname, HTTPS scheme)
  - Field mapping for every read-only method
  - get_fills() pagination logic
  - poll_order_events() → BrokerOrderEvent list
  - submission_enabled=False gate
  - submit_order(), cancel_order(), get_order()
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from trade_engine.alpaca_adapter import AlpacaAdapter, _ALPACA_PAPER_URL, _ALPACA_DATA_URL
from trade_engine.broker_types import (
    BrokerAccountState, BrokerFill, BrokerOrder, BrokerOrderAck,
    BrokerOrderEvent, BrokerPosition, BrokerQuote, BrokerCancelAck,
)
from trade_engine.execution_engine import BrokerSettlementIndeterminate, BrokerSubmissionIndeterminate
from trade_engine.models import (
    TradeIntent, Side, InstrumentType, OrderType, TimeInForce, IntentStatus
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _adapter(submission_enabled: bool = False) -> AlpacaAdapter:
    return AlpacaAdapter(
        "testkey", "testsecret",
        base_url="http://localhost:1234",
        data_url="http://localhost:5678",
        _allow_custom_url=True,
        submission_enabled=submission_enabled,
    )


def _mock_response(data, status=200) -> MagicMock:
    resp = MagicMock()
    resp.ok = (status < 400)
    resp.status_code = status
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def _intent(**overrides) -> TradeIntent:
    defaults = dict(
        intent_id="i1",
        account_id="acc1",
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
        limit_price=150.00,
        time_in_force=TimeInForce.DAY,
        strategy="test",
        thesis_version=None,
        strategy_config_hash=None,
        policy_hash=None,
        valid_until="2099-12-31T23:59:59Z",
        created_at="2026-09-14T00:00:00Z",
    )
    defaults.update(overrides)
    return TradeIntent(**defaults)


# ── Construction guards ──────────────────────────────────────────────────────

class TestConstructionGuards:
    def test_paper_false_raises(self):
        with pytest.raises(ValueError, match="paper=True"):
            AlpacaAdapter("k", "s", paper=False)

    def test_http_scheme_raises(self):
        with pytest.raises(ValueError, match="HTTPS"):
            AlpacaAdapter("k", "s", base_url="http://paper-api.alpaca.markets")

    def test_wrong_hostname_raises(self):
        with pytest.raises(ValueError, match="hostname"):
            AlpacaAdapter("k", "s", base_url="https://live-api.alpaca.markets")

    def test_correct_url_accepted(self):
        adapter = AlpacaAdapter("k", "s", base_url=_ALPACA_PAPER_URL)
        assert adapter._base_url == _ALPACA_PAPER_URL

    def test_allow_custom_url_bypasses_guard(self):
        adapter = AlpacaAdapter("k", "s", base_url="http://localhost:9", _allow_custom_url=True)
        assert "localhost" in adapter._base_url


# ── Auth headers ─────────────────────────────────────────────────────────────

class TestAuthHeaders:
    def test_headers_contain_keys(self):
        adapter = _adapter()
        headers = adapter._auth_headers
        assert headers["APCA-API-KEY-ID"] == "testkey"
        assert headers["APCA-API-SECRET-KEY"] == "testsecret"


# ── get_account_id ───────────────────────────────────────────────────────────

class TestGetAccountId:
    def test_returns_account_id(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({"id": "abc123"})):
            assert adapter.get_account_id() == "abc123"

    def test_validates_expected_account_id(self):
        adapter = AlpacaAdapter(
            "k", "s", base_url="http://localhost:1", _allow_custom_url=True,
            expected_account_id="expected-id",
        )
        with patch("requests.request", return_value=_mock_response({"id": "wrong-id"})):
            with pytest.raises(BrokerSettlementIndeterminate, match="mismatch"):
                adapter.get_account_id()

    def test_matching_expected_account_id_passes(self):
        adapter = AlpacaAdapter(
            "k", "s", base_url="http://localhost:1", _allow_custom_url=True,
            expected_account_id="right-id",
        )
        with patch("requests.request", return_value=_mock_response({"id": "right-id"})):
            assert adapter.get_account_id() == "right-id"


# ── get_broker_account ────────────────────────────────────────────────────────

class TestGetBrokerAccount:
    def test_maps_account_fields(self):
        adapter = _adapter()
        payload = {
            "id": "acc1",
            "cash": "10000.00",
            "portfolio_value": "15000.00",
            "buying_power": "9000.00",
        }
        with patch("requests.request", return_value=_mock_response(payload)):
            state = adapter.get_broker_account("acc1")
        assert isinstance(state, BrokerAccountState)
        assert state.account_id == "acc1"
        assert state.cash == 10000.0
        assert state.nav == 15000.0
        assert state.buying_power == 9000.0


# ── get_positions ─────────────────────────────────────────────────────────────

class TestGetPositions:
    def test_maps_position_fields(self):
        adapter = _adapter()
        payload = [
            {
                "symbol": "AAPL",
                "qty": "5",
                "avg_entry_price": "150.00",
                "current_price": "155.00",
                "market_value": "775.00",
                "asset_class": "us_equity",
            }
        ]
        with patch("requests.request", return_value=_mock_response(payload)):
            positions = adapter.get_positions("acc1")
        assert len(positions) == 1
        p = positions[0]
        assert isinstance(p, BrokerPosition)
        assert p.symbol == "AAPL"
        assert p.qty == 5.0
        assert p.avg_cost == 150.0
        assert p.market_price == 155.0
        assert p.market_value == 775.0

    def test_filters_non_equity(self):
        adapter = _adapter()
        payload = [
            {"symbol": "AAPL", "qty": "1", "avg_entry_price": "100", "asset_class": "us_equity"},
            {"symbol": "BTCUSD", "qty": "0.1", "avg_entry_price": "50000", "asset_class": "crypto"},
        ]
        with patch("requests.request", return_value=_mock_response(payload)):
            positions = adapter.get_positions("acc1")
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"

    def test_empty_positions(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])):
            positions = adapter.get_positions("acc1")
        assert positions == []


# ── get_open_orders ───────────────────────────────────────────────────────────

class TestGetOpenOrders:
    def test_maps_order_fields(self):
        adapter = _adapter()
        payload = [
            {
                "id": "broker-o1",
                "symbol": "AAPL",
                "side": "buy",
                "qty": "10",
                "filled_qty": "0",
                "status": "new",
                "limit_price": "149.00",
                "client_order_id": "client-1",
            }
        ]
        with patch("requests.request", return_value=_mock_response(payload)):
            orders = adapter.get_open_orders("acc1")
        assert len(orders) == 1
        o = orders[0]
        assert isinstance(o, BrokerOrder)
        assert o.broker_order_id == "broker-o1"
        assert o.symbol == "AAPL"
        assert o.side == "BUY"
        assert o.quantity == 10.0
        assert o.fill_qty == 0.0
        assert o.state == "WORKING"
        assert o.limit_price == 149.0
        assert o.client_order_id == "client-1"

    def test_normalized_states(self):
        adapter = _adapter()
        cases = [
            ("new", "WORKING"),
            ("accepted", "WORKING"),
            ("partially_filled", "PARTIALLY_FILLED"),
            ("filled", "FILLED"),
            ("canceled", "CANCELLED"),
            ("expired", "EXPIRED"),
            ("rejected", "REJECTED"),
        ]
        for raw, expected in cases:
            payload = [{
                "id": "o1", "symbol": "A", "side": "buy",
                "qty": "1", "filled_qty": "0", "status": raw,
            }]
            with patch("requests.request", return_value=_mock_response(payload)):
                orders = adapter.get_open_orders("acc1")
            assert orders[0].state == expected, f"raw={raw!r} → expected {expected!r}"


# ── get_fills ─────────────────────────────────────────────────────────────────

class TestGetFills:
    def _fill_payload(self, fill_id: str, order_id: str = "o1") -> dict:
        return {
            "id": fill_id,
            "order_id": order_id,
            "symbol": "AAPL",
            "side": "buy",
            "qty": "2",
            "price": "150.00",
            "transaction_time": "2026-09-14T14:30:00Z",
            "activity_type": "FILL",
        }

    def test_maps_fill_fields(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([self._fill_payload("f1")])):
            fills = adapter.get_fills("acc1")
        assert len(fills) == 1
        f = fills[0]
        assert isinstance(f, BrokerFill)
        assert f.broker_fill_id == "f1"
        assert f.broker_order_id == "o1"
        assert f.symbol == "AAPL"
        assert f.side == "BUY"
        assert f.qty == 2.0
        assert f.price == 150.0
        assert f.filled_at == "2026-09-14T14:30:00Z"

    def test_since_param_forwarded(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])) as mock_req:
            adapter.get_fills("acc1", since="2026-09-01T00:00:00Z")
        call_params = mock_req.call_args.kwargs.get("params") or mock_req.call_args[1].get("params")
        assert call_params["after"] == "2026-09-01T00:00:00Z"

    def test_pagination_stops_on_short_page(self):
        adapter = _adapter()
        page1 = [self._fill_payload(f"f{i}") for i in range(100)]
        page2 = [self._fill_payload("f100")]
        responses = [_mock_response(page1), _mock_response(page2)]
        with patch("requests.request", side_effect=responses):
            fills = adapter.get_fills("acc1")
        assert len(fills) == 101

    def test_empty_fills(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])):
            fills = adapter.get_fills("acc1")
        assert fills == []


# ── get_fills_for_order ───────────────────────────────────────────────────────

class TestGetFillsForOrder:
    def test_maps_fills(self):
        adapter = _adapter()
        payload = [{
            "id": "f1", "order_id": "o1", "symbol": "AAPL", "side": "buy",
            "qty": "5", "price": "200.00", "transaction_time": "2026-09-14T10:00:00Z",
        }]
        with patch("requests.request", return_value=_mock_response(payload)):
            fills = adapter.get_fills_for_order("o1")
        assert len(fills) == 1
        assert fills[0].broker_order_id == "o1"

    def test_order_id_param_forwarded(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])) as mock_req:
            adapter.get_fills_for_order("my-order-id")
        call_params = mock_req.call_args.kwargs.get("params") or mock_req.call_args[1].get("params")
        assert call_params["order_id"] == "my-order-id"


# ── get_quote ─────────────────────────────────────────────────────────────────

class TestGetQuote:
    def test_maps_quote_fields(self):
        adapter = _adapter()
        payload = {
            "quote": {
                "bp": 149.5,
                "ap": 150.0,
                "t": "2026-09-14T14:30:00Z",
            }
        }
        with patch("requests.request", return_value=_mock_response(payload)):
            quote = adapter.get_quote("AAPL")
        assert isinstance(quote, BrokerQuote)
        assert quote.bid == 149.5
        assert quote.ask == 150.0
        assert quote.symbol == "AAPL"
        assert quote.market_timestamp == "2026-09-14T14:30:00Z"
        assert quote.source == "alpaca"

    def test_uses_data_url(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({"quote": {"bp": 1, "ap": 2}})) as mock_req:
            adapter.get_quote("AAPL")
        url_used = mock_req.call_args.args[1] if mock_req.call_args.args else mock_req.call_args[0][1]
        assert "localhost:5678" in url_used  # data_url, not base_url

    def test_returns_none_on_error(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({}, status=404)):
            quote = adapter.get_quote("FAKESYMBOL")
        assert quote is None


# ── find_order_by_client_order_id ─────────────────────────────────────────────

class TestFindOrderByClientOrderId:
    def test_finds_order(self):
        adapter = _adapter()
        payload = {
            "id": "broker-o1", "symbol": "AAPL", "side": "buy",
            "qty": "3", "filled_qty": "0", "status": "new",
            "client_order_id": "my-client-id",
        }
        with patch("requests.request", return_value=_mock_response(payload)):
            order = adapter.find_order_by_client_order_id("my-client-id")
        assert order is not None
        assert order.broker_order_id == "broker-o1"
        assert order.client_order_id == "my-client-id"

    def test_returns_none_on_404(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({}, status=404)):
            order = adapter.find_order_by_client_order_id("missing")
        assert order is None


# ── poll_order_events ─────────────────────────────────────────────────────────

class TestPollOrderEvents:
    def test_returns_events_for_terminal_states(self):
        adapter = _adapter()
        payload = [
            {"id": "o1", "status": "filled", "client_order_id": "c1"},
            {"id": "o2", "status": "canceled", "client_order_id": "c2"},
        ]
        with patch("requests.request", return_value=_mock_response(payload)):
            events = adapter.poll_order_events("acc1")
        assert len(events) == 2
        types = {e.event_type for e in events}
        assert types == {"FILLED", "CANCELLED"}

    def test_ignores_informational_states(self):
        adapter = _adapter()
        payload = [
            {"id": "o1", "status": "new"},
            {"id": "o2", "status": "accepted"},
            {"id": "o3", "status": "filled", "client_order_id": "c3"},
        ]
        with patch("requests.request", return_value=_mock_response(payload)):
            events = adapter.poll_order_events("acc1")
        # only FILLED survives
        assert len(events) == 1
        assert events[0].event_type == "FILLED"

    def test_empty_when_no_orders(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])):
            events = adapter.poll_order_events("acc1")
        assert events == []

    def test_returns_empty_on_http_error(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({}, status=500)):
            events = adapter.poll_order_events("acc1")
        assert events == []


# ── Submission gate ───────────────────────────────────────────────────────────

class TestSubmissionGate:
    def test_raises_when_disabled(self):
        adapter = _adapter(submission_enabled=False)
        with pytest.raises(RuntimeError, match="submission_enabled=False"):
            adapter.submit_order(_intent())

    def test_does_not_raise_when_enabled(self):
        adapter = _adapter(submission_enabled=True)
        payload = {
            "id": "broker-o1",
            "client_order_id": "cid1",
            "status": "accepted",
            "submitted_at": "2026-09-14T14:00:00Z",
        }
        with patch("requests.request", return_value=_mock_response(payload)):
            ack = adapter.submit_order(_intent(), client_order_id="cid1")
        assert isinstance(ack, BrokerOrderAck)
        assert ack.broker_order_id == "broker-o1"
        assert ack.client_order_id == "cid1"
        assert ack.normalized_state == "WORKING"


# ── submit_order ──────────────────────────────────────────────────────────────

class TestSubmitOrder:
    def test_posts_correct_body(self):
        adapter = _adapter(submission_enabled=True)
        payload = {"id": "o1", "client_order_id": "c1", "status": "new", "submitted_at": None}
        with patch("requests.request", return_value=_mock_response(payload)) as mock_req:
            adapter.submit_order(_intent(symbol="TSLA", quantity=2, limit_price=200.0), client_order_id="c1")
        body = mock_req.call_args.kwargs.get("json") or mock_req.call_args[1].get("json")
        assert body["symbol"] == "TSLA"
        assert body["qty"] == "2"
        assert body["side"] == "buy"
        assert body["type"] == "limit"
        assert body["time_in_force"] == "day"
        assert body["limit_price"] == "200.0"
        assert body["client_order_id"] == "c1"

    def test_raises_submission_indeterminate_on_http_error(self):
        adapter = _adapter(submission_enabled=True)
        with patch("requests.request", return_value=_mock_response({}, status=500)):
            with pytest.raises(BrokerSubmissionIndeterminate):
                adapter.submit_order(_intent())

    def test_maps_ack_fields(self):
        adapter = _adapter(submission_enabled=True)
        payload = {
            "id": "broker-o1",
            "client_order_id": "cid-xyz",
            "status": "new",
            "submitted_at": "2026-09-14T14:30:00Z",
        }
        with patch("requests.request", return_value=_mock_response(payload)):
            ack = adapter.submit_order(_intent())
        assert ack.broker_order_id == "broker-o1"
        assert ack.normalized_state == "WORKING"
        assert ack.accepted_at == "2026-09-14T14:30:00Z"
        assert ack.raw_status == "new"


# ── cancel_order ──────────────────────────────────────────────────────────────

class TestCancelOrder:
    def test_cancel_accepted(self):
        adapter = _adapter()
        deleted_resp = _mock_response("", status=204)
        deleted_resp.ok = True
        order_resp = _mock_response({
            "id": "o1", "symbol": "AAPL", "side": "buy",
            "qty": "1", "filled_qty": "0", "status": "canceled",
        })
        with patch("requests.request", side_effect=[deleted_resp, order_resp]):
            ack = adapter.cancel_order("o1")
        assert isinstance(ack, BrokerCancelAck)
        assert ack.accepted is True
        assert ack.normalized_state == "CANCELLED"

    def test_cancel_404_not_accepted(self):
        adapter = _adapter()
        delete_resp = _mock_response("not found", status=404)
        # After 404 delete, get_order returns None
        order_resp = _mock_response("not found", status=404)
        with patch("requests.request", side_effect=[delete_resp, order_resp]):
            ack = adapter.cancel_order("missing-order")
        assert ack.accepted is False


# ── get_order ─────────────────────────────────────────────────────────────────

class TestGetOrder:
    def test_returns_order(self):
        adapter = _adapter()
        payload = {
            "id": "o1", "symbol": "AAPL", "side": "sell",
            "qty": "3", "filled_qty": "1", "status": "partially_filled",
            "limit_price": "155.00",
        }
        with patch("requests.request", return_value=_mock_response(payload)):
            order = adapter.get_order("o1")
        assert order is not None
        assert order.state == "PARTIALLY_FILLED"
        assert order.fill_qty == 1.0
        assert order.limit_price == 155.0

    def test_returns_none_on_404(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({}, status=404)):
            order = adapter.get_order("no-such-order")
        assert order is None


# ── HTTP error path ───────────────────────────────────────────────────────────

class TestHttpErrors:
    def test_non_2xx_raises_settlement_indeterminate(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({}, status=503)):
            with pytest.raises(BrokerSettlementIndeterminate):
                adapter.get_broker_account("acc1")

    def test_timeout_raises_settlement_indeterminate(self):
        import requests as req_lib
        adapter = _adapter()
        with patch("requests.request", side_effect=req_lib.exceptions.Timeout("timeout")):
            with pytest.raises(BrokerSettlementIndeterminate, match="timed out"):
                adapter.get_broker_account("acc1")
