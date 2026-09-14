"""Unit tests for AlpacaAdapter — all HTTP mocked, no live network calls (0294–0300).

Tests cover:
  - Construction guards: paper flag, base_url hostname/HTTPS, data_url hostname/HTTPS (0300)
  - Field mapping for every read-only method
  - Correct Alpaca endpoints: /v2/orders:by_client_order_id, /v2/account/activities/FILL (0297)
  - 204 No Content handling in cancel (0297)
  - requests.RequestException family → BrokerSettlementIndeterminate (0297)
  - account_id populated on all BrokerFill objects (0298)
  - poll_order_events() per-order refresh instead of watermark (0299)
  - Unknown Alpaca order status fails closed (0300)
  - submission_enabled=False gate
  - submit_order(), cancel_order(), get_order()
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call

from trade_engine.alpaca_adapter import AlpacaAdapter, _ALPACA_PAPER_URL, _ALPACA_DATA_URL
from trade_engine.broker_types import (
    BrokerAccountState, BrokerFill, BrokerOrder, BrokerOrderAck,
    BrokerOrderEvent, BrokerPosition, BrokerQuote, BrokerCancelAck,
)
from trade_engine.execution_engine import BrokerSettlementIndeterminate, BrokerSubmissionIndeterminate
from trade_engine.models import (
    TradeIntent, Side, InstrumentType, OrderType, TimeInForce,
)

import requests as req_lib


# ── Helpers ─────────────────────────────────────────────────────────────────

def _adapter(
    submission_enabled: bool = False,
    expected_account_id: Optional[str] = None,
) -> AlpacaAdapter:
    from typing import Optional
    return AlpacaAdapter(
        "testkey", "testsecret",
        base_url="http://localhost:1234",
        data_url="http://localhost:5678",
        _allow_custom_url=True,
        submission_enabled=submission_enabled,
        expected_account_id=expected_account_id,
    )


def _mock_response(data, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = (status < 400)
    resp.status_code = status
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def _mock_204() -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 204
    resp.text = ""
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


def _order_payload(
    order_id: str = "o1",
    status: str = "new",
    symbol: str = "AAPL",
    side: str = "buy",
    qty: str = "1",
    filled_qty: str = "0",
    client_order_id: str | None = None,
) -> dict:
    d = {
        "id": order_id, "symbol": symbol, "side": side,
        "qty": qty, "filled_qty": filled_qty, "status": status,
    }
    if client_order_id:
        d["client_order_id"] = client_order_id
    return d


# ── Construction guards ──────────────────────────────────────────────────────

class TestConstructionGuards:
    def test_paper_false_raises(self):
        with pytest.raises(ValueError, match="paper=True"):
            AlpacaAdapter("k", "s", paper=False)

    # base_url guards
    def test_base_http_scheme_raises(self):
        with pytest.raises(ValueError, match="HTTPS"):
            AlpacaAdapter("k", "s", base_url="http://paper-api.alpaca.markets")

    def test_base_wrong_hostname_raises(self):
        with pytest.raises(ValueError, match="hostname"):
            AlpacaAdapter("k", "s", base_url="https://live-api.alpaca.markets")

    def test_correct_base_url_accepted(self):
        adapter = AlpacaAdapter("k", "s", base_url=_ALPACA_PAPER_URL)
        assert adapter._base_url == _ALPACA_PAPER_URL

    # data_url guards (0300)
    def test_data_http_scheme_raises(self):
        with pytest.raises(ValueError, match="data_url.*HTTPS"):
            AlpacaAdapter("k", "s", base_url=_ALPACA_PAPER_URL,
                          data_url="http://data.alpaca.markets")

    def test_data_wrong_hostname_raises(self):
        with pytest.raises(ValueError, match="data_url.*hostname"):
            AlpacaAdapter("k", "s", base_url=_ALPACA_PAPER_URL,
                          data_url="https://wrong.alpaca.markets")

    def test_correct_data_url_accepted(self):
        adapter = AlpacaAdapter("k", "s", base_url=_ALPACA_PAPER_URL, data_url=_ALPACA_DATA_URL)
        assert adapter._data_url == _ALPACA_DATA_URL

    def test_allow_custom_url_bypasses_both_guards(self):
        adapter = AlpacaAdapter(
            "k", "s",
            base_url="http://localhost:9", data_url="http://localhost:10",
            _allow_custom_url=True,
        )
        assert "localhost:9" in adapter._base_url
        assert "localhost:10" in adapter._data_url

    def test_expected_account_id_pre_populates_cache(self):
        adapter = AlpacaAdapter(
            "k", "s", base_url=_ALPACA_PAPER_URL, expected_account_id="my-acct"
        )
        assert adapter._account_id == "my-acct"


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

    def test_caches_account_id(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({"id": "abc123"})):
            adapter.get_account_id()
        assert adapter._account_id == "abc123"

    def test_validates_expected_account_id(self):
        adapter = _adapter(expected_account_id="expected-id")
        with patch("requests.request", return_value=_mock_response({"id": "wrong-id"})):
            with pytest.raises(BrokerSettlementIndeterminate, match="mismatch"):
                adapter.get_account_id()

    def test_matching_expected_account_id_passes(self):
        adapter = _adapter(expected_account_id="right-id")
        with patch("requests.request", return_value=_mock_response({"id": "right-id"})):
            assert adapter.get_account_id() == "right-id"


# ── get_broker_account ────────────────────────────────────────────────────────

class TestGetBrokerAccount:
    def test_maps_account_fields(self):
        adapter = _adapter()
        payload = {
            "id": "acc1", "cash": "10000.00",
            "portfolio_value": "15000.00", "buying_power": "9000.00",
        }
        with patch("requests.request", return_value=_mock_response(payload)):
            state = adapter.get_broker_account("acc1")
        assert isinstance(state, BrokerAccountState)
        assert state.cash == 10000.0
        assert state.nav == 15000.0
        assert state.buying_power == 9000.0


# ── get_positions ─────────────────────────────────────────────────────────────

class TestGetPositions:
    def test_maps_position_fields(self):
        adapter = _adapter()
        payload = [{
            "symbol": "AAPL", "qty": "5", "avg_entry_price": "150.00",
            "current_price": "155.00", "market_value": "775.00", "asset_class": "us_equity",
        }]
        with patch("requests.request", return_value=_mock_response(payload)):
            positions = adapter.get_positions("acc1")
        assert len(positions) == 1
        p = positions[0]
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
            assert adapter.get_positions("acc1") == []


# ── get_open_orders ───────────────────────────────────────────────────────────

class TestGetOpenOrders:
    def test_maps_order_fields(self):
        adapter = _adapter()
        payload = [{
            "id": "broker-o1", "symbol": "AAPL", "side": "buy",
            "qty": "10", "filled_qty": "0", "status": "new",
            "limit_price": "149.00", "client_order_id": "client-1",
        }]
        with patch("requests.request", return_value=_mock_response(payload)):
            orders = adapter.get_open_orders("acc1")
        assert len(orders) == 1
        o = orders[0]
        assert o.broker_order_id == "broker-o1"
        assert o.side == "BUY"
        assert o.state == "WORKING"
        assert o.limit_price == 149.0
        assert o.client_order_id == "client-1"

    def test_normalized_states(self):
        adapter = _adapter()
        cases = [
            ("new", "WORKING"), ("accepted", "WORKING"),
            ("partially_filled", "PARTIALLY_FILLED"), ("filled", "FILLED"),
            ("canceled", "CANCELLED"), ("expired", "EXPIRED"), ("rejected", "REJECTED"),
        ]
        for raw, expected in cases:
            payload = [{"id": "o1", "symbol": "A", "side": "buy",
                        "qty": "1", "filled_qty": "0", "status": raw}]
            with patch("requests.request", return_value=_mock_response(payload)):
                orders = adapter.get_open_orders("acc1")
            assert orders[0].state == expected, f"raw={raw!r}"

    def test_unknown_status_fails_closed(self):
        """Unknown Alpaca status raises BrokerSettlementIndeterminate (0300)."""
        adapter = _adapter()
        payload = [{"id": "o1", "symbol": "A", "side": "buy",
                    "qty": "1", "filled_qty": "0", "status": "completely_made_up_status"}]
        with patch("requests.request", return_value=_mock_response(payload)):
            with pytest.raises(BrokerSettlementIndeterminate, match="unknown Alpaca order status"):
                adapter.get_open_orders("acc1")


# ── get_fills ─────────────────────────────────────────────────────────────────

class TestGetFills:
    def _fill_payload(self, fill_id: str, order_id: str = "o1") -> dict:
        return {
            "id": fill_id, "order_id": order_id, "symbol": "AAPL",
            "side": "buy", "qty": "2", "price": "150.00",
            "transaction_time": "2026-09-14T14:30:00Z",
        }

    def test_uses_specific_fill_endpoint(self):
        """get_fills() must call /v2/account/activities/FILL, not the generic endpoint (0297)."""
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])) as mock_req:
            adapter.get_fills("acc1")
        url = mock_req.call_args.args[1] if mock_req.call_args.args else mock_req.call_args[0][1]
        assert "/v2/account/activities/FILL" in url
        # Must NOT use activity_type parameter
        params = mock_req.call_args.kwargs.get("params") or mock_req.call_args[1].get("params", {})
        assert "activity_type" not in params

    def test_maps_fill_fields(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([self._fill_payload("f1")])):
            fills = adapter.get_fills("acc1")
        assert len(fills) == 1
        f = fills[0]
        assert f.broker_fill_id == "f1"
        assert f.broker_order_id == "o1"
        assert f.symbol == "AAPL"
        assert f.side == "BUY"
        assert f.qty == 2.0
        assert f.price == 150.0
        assert f.account_id == "acc1"

    def test_since_param_forwarded(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])) as mock_req:
            adapter.get_fills("acc1", since="2026-09-01T00:00:00Z")
        params = mock_req.call_args.kwargs.get("params") or mock_req.call_args[1].get("params")
        assert params["after"] == "2026-09-01T00:00:00Z"

    def test_pagination_stops_on_short_page(self):
        adapter = _adapter()
        page1 = [self._fill_payload(f"f{i}") for i in range(100)]
        page2 = [self._fill_payload("f100")]
        with patch("requests.request", side_effect=[_mock_response(page1), _mock_response(page2)]):
            fills = adapter.get_fills("acc1")
        assert len(fills) == 101

    def test_empty_fills(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])):
            assert adapter.get_fills("acc1") == []


# ── get_fills_for_order ───────────────────────────────────────────────────────

class TestGetFillsForOrder:
    def test_uses_specific_fill_endpoint(self):
        """get_fills_for_order() must call /v2/account/activities/FILL (0297)."""
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])) as mock_req:
            adapter.get_fills_for_order("o1")
        url = mock_req.call_args.args[1] if mock_req.call_args.args else mock_req.call_args[0][1]
        assert "/v2/account/activities/FILL" in url

    def test_order_id_param_forwarded(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response([])) as mock_req:
            adapter.get_fills_for_order("my-order-id")
        params = mock_req.call_args.kwargs.get("params") or mock_req.call_args[1].get("params")
        assert params["order_id"] == "my-order-id"

    def test_account_id_populated_from_cache(self):
        """Fills from get_fills_for_order() carry the cached account_id, not None (0298)."""
        adapter = _adapter(expected_account_id="paper-acct-123")
        payload = [{
            "id": "f1", "order_id": "o1", "symbol": "AAPL", "side": "buy",
            "qty": "5", "price": "200.00", "transaction_time": "2026-09-14T10:00:00Z",
        }]
        with patch("requests.request", return_value=_mock_response(payload)):
            fills = adapter.get_fills_for_order("o1")
        assert len(fills) == 1
        assert fills[0].account_id == "paper-acct-123"

    def test_account_id_populated_after_get_account_id(self):
        """account_id cache set by get_account_id() flows into get_fills_for_order() (0298)."""
        adapter = _adapter()  # no expected_account_id at construction
        payload_account = {"id": "live-acct-456", "cash": "0", "portfolio_value": "0", "buying_power": "0"}
        payload_fills = [{
            "id": "f1", "order_id": "o1", "symbol": "AAPL", "side": "buy",
            "qty": "1", "price": "100.00", "transaction_time": "2026-09-14T10:00:00Z",
        }]
        with patch("requests.request", side_effect=[
            _mock_response(payload_account),
            _mock_response(payload_fills),
        ]):
            adapter.get_account_id()
            fills = adapter.get_fills_for_order("o1")
        assert fills[0].account_id == "live-acct-456"

    def test_raises_when_no_account_id_available(self):
        """_map_fill() raises BrokerSettlementIndeterminate when account_id is None (0304)."""
        adapter = _adapter()  # no expected_account_id; get_account_id() never called
        payload = [{
            "id": "f1", "order_id": "o1", "symbol": "AAPL", "side": "buy",
            "qty": "1", "price": "100.00", "transaction_time": "2026-09-14T10:00:00Z",
        }]
        with patch("requests.request", return_value=_mock_response(payload)):
            with pytest.raises(BrokerSettlementIndeterminate, match="account_id is None"):
                adapter.get_fills_for_order("o1")

    def test_paginates_via_page_token(self):
        """get_fills_for_order() follows page_token when first page is full (0304)."""
        adapter = _adapter(expected_account_id="acct-1")

        def _fill(fid: str) -> dict:
            return {
                "id": fid, "order_id": "o1", "symbol": "AAPL", "side": "buy",
                "qty": "1", "price": "100.00", "transaction_time": "2026-09-14T10:00:00Z",
            }

        # First page returns 100 fills (full page) → adapter must request page 2
        page1 = [_fill(f"f{i}") for i in range(100)]
        page2 = [_fill("f100")]  # partial page → stop

        with patch("requests.request", side_effect=[
            _mock_response(page1),
            _mock_response(page2),
        ]) as mock_req:
            fills = adapter.get_fills_for_order("o1")

        assert len(fills) == 101
        # Second call must include page_token from last item of page 1
        second_params = mock_req.call_args_list[1].kwargs.get("params") or mock_req.call_args_list[1][1].get("params")
        assert second_params["page_token"] == "f99"


# ── get_quote ─────────────────────────────────────────────────────────────────

class TestGetQuote:
    def test_maps_quote_fields(self):
        adapter = _adapter()
        payload = {"quote": {"bp": 149.5, "ap": 150.0, "t": "2026-09-14T14:30:00Z"}}
        with patch("requests.request", return_value=_mock_response(payload)):
            quote = adapter.get_quote("AAPL")
        assert quote.bid == 149.5
        assert quote.ask == 150.0
        assert quote.symbol == "AAPL"
        assert quote.source == "alpaca"

    def test_uses_data_url(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({"quote": {"bp": 1, "ap": 2}})) as mock_req:
            adapter.get_quote("AAPL")
        url = mock_req.call_args.args[1] if mock_req.call_args.args else mock_req.call_args[0][1]
        assert "localhost:5678" in url  # data_url, not base_url

    def test_returns_none_on_error(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({}, status=404)):
            assert adapter.get_quote("FAKESYMBOL") is None


# ── find_order_by_client_order_id ─────────────────────────────────────────────

class TestFindOrderByClientOrderId:
    def test_uses_correct_endpoint(self):
        """Must call GET /v2/orders:by_client_order_id?client_order_id=<id> (0297)."""
        adapter = _adapter()
        payload = _order_payload("broker-o1", client_order_id="my-client-id")
        with patch("requests.request", return_value=_mock_response(payload)) as mock_req:
            adapter.find_order_by_client_order_id("my-client-id")
        url = mock_req.call_args.args[1] if mock_req.call_args.args else mock_req.call_args[0][1]
        assert "/v2/orders:by_client_order_id" in url
        params = mock_req.call_args.kwargs.get("params") or mock_req.call_args[1].get("params")
        assert params["client_order_id"] == "my-client-id"

    def test_finds_order(self):
        adapter = _adapter()
        payload = _order_payload("broker-o1", client_order_id="my-client-id")
        with patch("requests.request", return_value=_mock_response(payload)):
            order = adapter.find_order_by_client_order_id("my-client-id")
        assert order.broker_order_id == "broker-o1"
        assert order.client_order_id == "my-client-id"

    def test_returns_none_on_404(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({}, status=404)):
            assert adapter.find_order_by_client_order_id("missing") is None


# ── poll_order_events (0299) ──────────────────────────────────────────────────

class TestPollOrderEvents:
    def test_returns_empty_when_no_tracked_orders_and_broker_empty(self):
        adapter = _adapter()
        # First call seeds from broker open orders (empty), then checks tracked set
        with patch("requests.request", return_value=_mock_response([])):
            events = adapter.poll_order_events("acc1")
        assert events == []

    def test_seeds_tracking_from_broker_on_first_call(self):
        """On first poll, open broker orders are added to _tracked_broker_order_ids (0299)."""
        adapter = _adapter()
        open_orders = [_order_payload("o1"), _order_payload("o2")]
        with patch("requests.request", return_value=_mock_response(open_orders)):
            events = adapter.poll_order_events("acc1")
        assert "o1" in adapter._tracked_broker_order_ids
        assert "o2" in adapter._tracked_broker_order_ids
        assert events == []  # both still open — no events

    def test_emits_filled_event_when_order_leaves_open_set(self):
        """Order that disappears from broker open set → get_order() → FILLED event (0299)."""
        adapter = _adapter()
        adapter._poll_seeded = True
        adapter._tracked_broker_order_ids = {"o1"}
        # get_open_orders returns empty (o1 not open anymore)
        open_resp = _mock_response([])
        # get_order("o1") returns filled
        order_resp = _mock_response(_order_payload("o1", status="filled"))
        with patch("requests.request", side_effect=[open_resp, order_resp]):
            events = adapter.poll_order_events("acc1")
        assert len(events) == 1
        assert events[0].event_type == "FILLED"
        assert events[0].broker_order_id == "o1"
        # Removed from tracking after terminal event
        assert "o1" not in adapter._tracked_broker_order_ids

    def test_emits_cancelled_event(self):
        adapter = _adapter()
        adapter._poll_seeded = True
        adapter._tracked_broker_order_ids = {"o1"}
        open_resp = _mock_response([])
        order_resp = _mock_response(_order_payload("o1", status="canceled"))
        with patch("requests.request", side_effect=[open_resp, order_resp]):
            events = adapter.poll_order_events("acc1")
        assert len(events) == 1
        assert events[0].event_type == "CANCELLED"

    def test_still_open_orders_kept_in_tracking_no_event(self):
        """Orders still in broker open set produce no event and stay tracked (0299)."""
        adapter = _adapter()
        adapter._poll_seeded = True
        adapter._tracked_broker_order_ids = {"o1"}
        open_resp = _mock_response([_order_payload("o1", status="new")])
        with patch("requests.request", return_value=open_resp):
            events = adapter.poll_order_events("acc1")
        assert events == []
        assert "o1" in adapter._tracked_broker_order_ids

    def test_connectivity_error_raises_settlement_indeterminate(self):
        """get_open_orders() failure during normal poll propagates — no silent empty (0301)."""
        adapter = _adapter()
        adapter._poll_seeded = True
        adapter._tracked_broker_order_ids = {"o1"}
        with patch("requests.request", return_value=_mock_response({}, status=503)):
            with pytest.raises(BrokerSettlementIndeterminate):
                adapter.poll_order_events("acc1")
        # tracking set is unchanged — order stays tracked for next cycle
        assert "o1" in adapter._tracked_broker_order_ids

    def test_seed_failure_leaves_poll_unseeded(self):
        """get_open_orders() failure during seed propagates and leaves _poll_seeded=False (0301)."""
        adapter = _adapter()
        assert adapter._poll_seeded is False
        with patch("requests.request", return_value=_mock_response({}, status=503)):
            with pytest.raises(BrokerSettlementIndeterminate):
                adapter.poll_order_events("acc1")
        assert adapter._poll_seeded is False

    def test_get_order_failure_after_order_leaves_open_set_propagates(self):
        """get_order() raising after order disappears from open set propagates — not silent (0305)."""
        adapter = _adapter()
        adapter._poll_seeded = True
        adapter._tracked_broker_order_ids = {"o1"}
        open_resp = _mock_response([])  # o1 no longer open
        get_order_resp = _mock_response({}, status=503)  # get_order fails
        with patch("requests.request", side_effect=[open_resp, get_order_resp]):
            with pytest.raises(BrokerSettlementIndeterminate):
                adapter.poll_order_events("acc1")

    def test_order_submitted_then_polled_as_filled(self):
        """submit_order() registers broker_order_id; next poll detects fill (0299)."""
        adapter = _adapter(submission_enabled=True)
        submit_resp = _mock_response({
            "id": "broker-o1", "client_order_id": "c1",
            "status": "new", "submitted_at": None,
        })
        with patch("requests.request", return_value=submit_resp):
            adapter.submit_order(_intent(), client_order_id="c1")
        assert "broker-o1" in adapter._tracked_broker_order_ids

        # Simulate next poll: seed (already done), open orders empty, get_order → filled
        adapter._poll_seeded = True
        open_resp = _mock_response([])
        order_resp = _mock_response(_order_payload("broker-o1", status="filled", client_order_id="c1"))
        with patch("requests.request", side_effect=[open_resp, order_resp]):
            events = adapter.poll_order_events("acc1")
        assert len(events) == 1
        assert events[0].event_type == "FILLED"
        assert events[0].broker_order_id == "broker-o1"


# ── Submission gate ───────────────────────────────────────────────────────────

class TestSubmissionGate:
    def test_raises_when_disabled(self):
        adapter = _adapter(submission_enabled=False)
        with pytest.raises(RuntimeError, match="submission_enabled=False"):
            adapter.submit_order(_intent())

    def test_does_not_raise_when_enabled(self):
        adapter = _adapter(submission_enabled=True)
        payload = {
            "id": "broker-o1", "client_order_id": "cid1",
            "status": "accepted", "submitted_at": "2026-09-14T14:00:00Z",
        }
        with patch("requests.request", return_value=_mock_response(payload)):
            ack = adapter.submit_order(_intent(), client_order_id="cid1")
        assert ack.broker_order_id == "broker-o1"
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

    def test_raises_submission_indeterminate_on_connection_reset(self):
        """Connection reset during POST → BrokerSubmissionIndeterminate, not bare exception (0297)."""
        adapter = _adapter(submission_enabled=True)
        with patch("requests.request", side_effect=req_lib.exceptions.ConnectionError("reset")):
            with pytest.raises(BrokerSubmissionIndeterminate):
                adapter.submit_order(_intent())

    def test_maps_ack_fields(self):
        adapter = _adapter(submission_enabled=True)
        payload = {
            "id": "broker-o1", "client_order_id": "cid-xyz",
            "status": "new", "submitted_at": "2026-09-14T14:30:00Z",
        }
        with patch("requests.request", return_value=_mock_response(payload)):
            ack = adapter.submit_order(_intent())
        assert ack.broker_order_id == "broker-o1"
        assert ack.normalized_state == "WORKING"
        assert ack.accepted_at == "2026-09-14T14:30:00Z"
        assert ack.raw_status == "new"

    def test_unknown_status_in_ack_fails_closed(self):
        """Unknown status in submit ACK raises rather than silently defaulting (0300)."""
        adapter = _adapter(submission_enabled=True)
        payload = {"id": "o1", "client_order_id": None, "status": "unknown_future_status"}
        with patch("requests.request", return_value=_mock_response(payload)):
            with pytest.raises(BrokerSettlementIndeterminate, match="unknown Alpaca order status"):
                adapter.submit_order(_intent())


# ── cancel_order ──────────────────────────────────────────────────────────────

class TestCancelOrder:
    def test_cancel_returns_204_accepted(self):
        """Alpaca returns 204 No Content on success; adapter must not call resp.json() (0297)."""
        adapter = _adapter()
        order_resp = _mock_response(_order_payload("o1", status="canceled"))
        with patch("requests.request", side_effect=[_mock_204(), order_resp]):
            ack = adapter.cancel_order("o1")
        assert isinstance(ack, BrokerCancelAck)
        assert ack.accepted is True
        assert ack.normalized_state == "CANCELLED"

    def test_cancel_404_raises_when_get_also_404(self):
        """DELETE 404 + GET 404 → BrokerSettlementIndeterminate (0303)."""
        adapter = _adapter()
        delete_resp = _mock_response("not found", status=404)
        order_resp = _mock_response("not found", status=404)
        with patch("requests.request", side_effect=[delete_resp, order_resp]):
            with pytest.raises(BrokerSettlementIndeterminate, match="no record"):
                adapter.cancel_order("missing-order")

    def test_cancel_404_but_get_returns_terminal_state(self):
        """DELETE 404 (already closed) + GET returns real state → valid ack (0303)."""
        adapter = _adapter()
        delete_resp = _mock_response("not found", status=404)
        order_resp = _mock_response(_order_payload("o1", status="expired"))
        with patch("requests.request", side_effect=[delete_resp, order_resp]):
            ack = adapter.cancel_order("o1")
        assert ack.accepted is False
        assert ack.normalized_state == "EXPIRED"


# ── get_order ─────────────────────────────────────────────────────────────────

class TestGetOrder:
    def test_returns_order(self):
        adapter = _adapter()
        payload = _order_payload("o1", status="partially_filled", qty="3", filled_qty="1")
        payload["limit_price"] = "155.00"
        with patch("requests.request", return_value=_mock_response(payload)):
            order = adapter.get_order("o1")
        assert order.state == "PARTIALLY_FILLED"
        assert order.fill_qty == 1.0
        assert order.limit_price == 155.0

    def test_returns_none_on_404(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({}, status=404)):
            assert adapter.get_order("no-such-order") is None


# ── HTTP error paths ──────────────────────────────────────────────────────────

class TestHttpErrors:
    def test_non_2xx_raises_settlement_indeterminate(self):
        adapter = _adapter()
        with patch("requests.request", return_value=_mock_response({}, status=503)):
            with pytest.raises(BrokerSettlementIndeterminate):
                adapter.get_broker_account("acc1")

    def test_timeout_raises_settlement_indeterminate(self):
        adapter = _adapter()
        with patch("requests.request", side_effect=req_lib.exceptions.Timeout("timeout")):
            with pytest.raises(BrokerSettlementIndeterminate):
                adapter.get_broker_account("acc1")

    def test_connection_error_raises_settlement_indeterminate(self):
        """Connection reset / DNS failure → BrokerSettlementIndeterminate (0297)."""
        adapter = _adapter()
        with patch("requests.request", side_effect=req_lib.exceptions.ConnectionError("reset")):
            with pytest.raises(BrokerSettlementIndeterminate):
                adapter.get_broker_account("acc1")

    def test_204_does_not_raise(self):
        """A 204 on DELETE is a success; no json() call, no exception (0297)."""
        adapter = _adapter()
        order_resp = _mock_response(_order_payload("o1", status="canceled"))
        with patch("requests.request", side_effect=[_mock_204(), order_resp]):
            ack = adapter.cancel_order("o1")
        assert ack.accepted is True

    def test_transport_error_appended_to_recent_api_calls(self):
        """ConnectionError is recorded in _recent_api_calls with status_code=None (0321)."""
        adapter = _adapter()
        with patch("requests.request", side_effect=req_lib.exceptions.ConnectionError("reset")):
            with pytest.raises(BrokerSettlementIndeterminate):
                adapter.get_broker_account("acc1")
        assert len(adapter._recent_api_calls) == 1
        rec = adapter._recent_api_calls[0]
        assert rec["status_code"] is None
        assert rec["method"] == "GET"
        assert rec["path"] == "/v2/account"
        assert rec["error_type"] == "ConnectionError"


# ── submit_order pre-flight validation (0311) ─────────────────────────────────

class TestSubmitOrderPreFlight:
    """AlpacaAdapter.submit_order() rejects non-EQUITY, non-LIMIT, non-DAY, non-BUY/SELL, non-integer qty."""

    def _submit_adapter(self) -> AlpacaAdapter:
        return _adapter(submission_enabled=True)

    def test_non_equity_raises(self):
        adapter = self._submit_adapter()
        with pytest.raises(ValueError, match="EQUITY"):
            adapter.submit_order(_intent(instrument_type=InstrumentType.OPTION))

    def test_non_limit_raises(self):
        adapter = self._submit_adapter()
        with pytest.raises(ValueError, match="LIMIT"):
            adapter.submit_order(_intent(order_type=OrderType.MARKET))

    def test_non_day_tif_raises(self):
        from trade_engine.models import TimeInForce as TIF
        adapter = self._submit_adapter()
        with pytest.raises(ValueError, match="DAY"):
            adapter.submit_order(_intent(time_in_force=TIF.GTC))

    def test_non_buy_sell_side_raises(self):
        adapter = self._submit_adapter()
        with pytest.raises(ValueError, match="BUY or SELL"):
            adapter.submit_order(_intent(side=Side.SELL_TO_OPEN))

    def test_zero_quantity_raises(self):
        adapter = self._submit_adapter()
        with pytest.raises(ValueError, match="quantity"):
            adapter.submit_order(_intent(quantity=0.0))

    def test_fractional_quantity_raises(self):
        adapter = self._submit_adapter()
        with pytest.raises(ValueError, match="quantity"):
            adapter.submit_order(_intent(quantity=1.5))

    def test_valid_buy_passes_preflight(self):
        adapter = self._submit_adapter()
        order_payload = {
            "id": "broker-123", "symbol": "AAPL", "side": "buy",
            "qty": "1", "filled_qty": "0", "status": "new",
            "client_order_id": "c1",
        }
        with patch("requests.request", return_value=_mock_response(order_payload, status=200)):
            ack = adapter.submit_order(_intent(side=Side.BUY, quantity=1.0))
        assert ack.broker_order_id == "broker-123"


# ── get_market_clock (0326) ───────────────────────────────────────────────────

class TestGetMarketClock:
    """get_market_clock() must call GET /v2/clock (not /v1/clock) and map the response."""

    def test_calls_v2_clock_endpoint(self):
        """Assert the correct /v2/clock path is passed to _request (0326)."""
        adapter = _adapter()
        clock_payload = {"is_open": True, "next_open": "2026-09-15T13:30:00Z", "next_close": "2026-09-14T20:00:00Z"}
        with patch("requests.request", return_value=_mock_response(clock_payload)) as mock_req:
            result = adapter.get_market_clock()
        # Verify the URL contains /v2/clock, not /v1/clock
        called_url = mock_req.call_args[1].get("url") or mock_req.call_args[0][1]
        assert "/v2/clock" in called_url, f"Expected /v2/clock in URL, got: {called_url}"
        assert "/v1/clock" not in called_url

    def test_returns_is_open_true(self):
        adapter = _adapter()
        payload = {"is_open": True, "next_open": "", "next_close": "2026-09-14T20:00:00Z"}
        with patch("requests.request", return_value=_mock_response(payload)):
            result = adapter.get_market_clock()
        assert result["is_open"] is True
        assert result["next_close"] == "2026-09-14T20:00:00Z"

    def test_returns_is_open_false(self):
        adapter = _adapter()
        payload = {"is_open": False, "next_open": "2026-09-15T13:30:00Z", "next_close": ""}
        with patch("requests.request", return_value=_mock_response(payload)):
            result = adapter.get_market_clock()
        assert result["is_open"] is False
        assert result["next_open"] == "2026-09-15T13:30:00Z"
