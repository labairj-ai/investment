"""AlpacaAdapter: external broker adapter for Alpaca paper trading (0287, 0291, 0294, 0295).

Paper-only guard (0291): construction validates that base_url uses HTTPS and has the exact
hostname paper-api.alpaca.markets, and data_url uses HTTPS with exact hostname
data.alpaca.markets (0300). Substring checks are insufficient.

Read-only methods (0294): account identity, positions, open orders, fills, quote.
Order mutation (0295): submit_order, cancel_order, get_order, poll_order_events,
behind a submission_enabled=False safety gate.

API contract fixes (0297): correct client-order lookup endpoint, FILL activity endpoint,
204 No Content handling, RequestException catch-all.
Fill account identity (0298): _account_id cache propagated to all BrokerFill objects.
Polling correctness (0299): per-order refresh instead of submitted-at watermark.
Hardening (0300): data_url allowlist, fail-closed on unknown order statuses.
"""
from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

_log = logging.getLogger(__name__)

import requests

from .broker_adapter import BrokerAdapter
from .broker_types import (
    BrokerAccountState, BrokerCancelAck, BrokerFill, BrokerOrder,
    BrokerOrderAck, BrokerOrderEvent, BrokerPosition, BrokerQuote,
)
from .execution_engine import BrokerSettlementIndeterminate, BrokerSubmissionIndeterminate
from .models import InstrumentType, OrderType, Side, TimeInForce, TradeIntent

_ALPACA_PAPER_HOSTNAME = "paper-api.alpaca.markets"
_ALPACA_DATA_HOSTNAME = "data.alpaca.markets"
_ALPACA_PAPER_URL = f"https://{_ALPACA_PAPER_HOSTNAME}"
_ALPACA_DATA_URL = f"https://{_ALPACA_DATA_HOSTNAME}"

# Mapping from Alpaca native trade_updates event types to normalized BrokerOrderEvent
# event_type values (0290). None = informational only; no order state change required.
_ALPACA_NATIVE_TO_NORMALIZED: dict[str, str | None] = {
    "fill":            "FILLED",
    "partial_fill":    "PARTIALLY_FILLED",
    "canceled":        "CANCELLED",
    "expired":         "EXPIRED",
    "rejected":        "REJECTED",
    # Informational lifecycle notifications — adapters may safely ignore these:
    "new":             None,
    "accepted":        None,
    "pending_new":     None,
    "replaced":        None,
    "pending_cancel":  None,
    "pending_replace": None,
    "held":            None,
    "done_for_day":    None,
    "suspended":       None,
}

# Full documented Alpaca order status → normalized BrokerOrderState (0300).
# Any status NOT in this map causes _normalize_order_status() to fail closed —
# unknown broker state must never silently become WORKING.
_ALPACA_ORDER_STATUS_MAP: dict[str, str] = {
    "new":                  "WORKING",
    "accepted":             "WORKING",
    "accepted_for_bidding": "WORKING",
    "pending_new":          "WORKING",
    "pending_cancel":       "WORKING",   # cancel in flight; still open
    "pending_replace":      "WORKING",   # replace in flight; still open
    "held":                 "WORKING",
    "suspended":            "WORKING",
    "stopped":              "WORKING",
    "calculated":           "WORKING",   # post-market processing
    "partially_filled":     "PARTIALLY_FILLED",
    "filled":               "FILLED",
    "canceled":             "CANCELLED",
    "replaced":             "CANCELLED",
    "expired":              "EXPIRED",
    "done_for_day":         "EXPIRED",
    "rejected":             "REJECTED",
}

_REQUEST_TIMEOUT = 10  # seconds


def _normalize_order_status(raw: str) -> str:
    """Return normalized BrokerOrderState for a raw Alpaca status string (0300).

    Raises BrokerSettlementIndeterminate on any status not in the explicit map.
    Callers must NOT use .get(raw, default) — unknown states fail closed.
    """
    try:
        return _ALPACA_ORDER_STATUS_MAP[raw]
    except KeyError:
        raise BrokerSettlementIndeterminate(
            f"AlpacaAdapter: unknown Alpaca order status {raw!r} — failing closed. "
            f"Update _ALPACA_ORDER_STATUS_MAP when Alpaca documents this status."
        )


class AlpacaAdapter(BrokerAdapter):
    """Alpaca broker adapter — paper trading only (0287, 0291, 0294, 0295).

    Construction guards (0291, 0300):
      - paper=True enforced unconditionally
      - base_url: HTTPS + exact hostname paper-api.alpaca.markets
      - data_url: HTTPS + exact hostname data.alpaca.markets
    Use _allow_custom_url=True ONLY in unit tests that need a local HTTP server.

    Submission gate (0295): submit_order() raises RuntimeError unless
    submission_enabled=True is passed at construction time.

    Account identity cache (0298): _account_id is set from expected_account_id at
    construction, or from the broker's response in get_account_id(). All BrokerFill
    objects carry this value so apply_broker_fill() account validation always passes.

    Order tracking for poll correctness (0299): _tracked_broker_order_ids stores IDs
    of orders submitted through this adapter. poll_order_events() refreshes each tracked
    order individually via get_order() rather than using a submitted-at watermark, which
    Alpaca's `after` parameter does not support for state-change detection.
    """

    requires_market_timestamp = True  # Alpaca supplies exchange observation time

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = _ALPACA_PAPER_URL,
        data_url: str = _ALPACA_DATA_URL,
        *,
        paper: bool = True,
        expected_account_id: Optional[str] = None,
        submission_enabled: bool = False,
        _allow_custom_url: bool = False,  # test-only escape hatch; never set in production
    ) -> None:
        if not paper:
            raise ValueError(
                "AlpacaAdapter only supports paper=True; live trading is not yet implemented"
            )
        if not _allow_custom_url:
            _parsed_base = urllib.parse.urlparse(base_url)
            if _parsed_base.scheme != "https":
                raise ValueError(
                    f"AlpacaAdapter: base_url must use HTTPS; "
                    f"got scheme {_parsed_base.scheme!r} in {base_url!r}"
                )
            if _parsed_base.hostname != _ALPACA_PAPER_HOSTNAME:
                raise ValueError(
                    f"AlpacaAdapter: base_url hostname must be exactly "
                    f"{_ALPACA_PAPER_HOSTNAME!r}; got {_parsed_base.hostname!r} in {base_url!r}. "
                    f"Set base_url to {_ALPACA_PAPER_URL!r} for paper trading."
                )
            _parsed_data = urllib.parse.urlparse(data_url)
            if _parsed_data.scheme != "https":
                raise ValueError(
                    f"AlpacaAdapter: data_url must use HTTPS; "
                    f"got scheme {_parsed_data.scheme!r} in {data_url!r}"
                )
            if _parsed_data.hostname != _ALPACA_DATA_HOSTNAME:
                raise ValueError(
                    f"AlpacaAdapter: data_url hostname must be exactly "
                    f"{_ALPACA_DATA_HOSTNAME!r}; got {_parsed_data.hostname!r} in {data_url!r}. "
                    f"Set data_url to {_ALPACA_DATA_URL!r}."
                )
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._data_url = data_url.rstrip("/")
        self._expected_account_id = expected_account_id
        self._submission_enabled = submission_enabled
        # Verified paper account ID — populated from expected_account_id or get_account_id() (0298)
        self._account_id: Optional[str] = expected_account_id
        # Broker order IDs submitted through this adapter; used by poll_order_events() (0299)
        self._tracked_broker_order_ids: set[str] = set()
        # Seeded from broker open orders on first poll so restart recovers tracked state (0299)
        self._poll_seeded: bool = False
        # Rolling log of recent API calls for X-Request-ID persistence and cycle scorecard (0316)
        self._recent_api_calls: list[dict] = []

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    @property
    def _auth_headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._api_secret,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        base: str | None = None,
        params: dict | None = None,
        json: dict | None = None,
    ) -> dict | list | None:
        url = f"{base or self._base_url}{path}"
        try:
            resp = requests.request(
                method, url,
                headers=self._auth_headers,
                params=params,
                json=json,
                timeout=_REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException as exc:
            # Catch the full RequestException family (Timeout, ConnectionError, etc.) so
            # a connection reset during POST becomes BrokerSettlementIndeterminate rather
            # than an unhandled exception (0297).
            # Record transport failure in call log before re-raising so broker_api_errors
            # counts it (status_code=None distinguishes transport vs HTTP errors) (0321).
            self._recent_api_calls.append({
                "method": method,
                "path": path,
                "status_code": None,
                "request_id": "",
                "called_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
            })
            if len(self._recent_api_calls) > 200:
                self._recent_api_calls = self._recent_api_calls[-200:]
            raise BrokerSettlementIndeterminate(
                f"AlpacaAdapter: {method} {path} request failed: {exc}"
            ) from exc
        # Log X-Request-ID for every call; Alpaca recommends retaining it for support (0316).
        req_id = resp.headers.get("x-request-id") or resp.headers.get("X-Request-Id", "")
        if req_id:
            _log.debug("AlpacaAdapter %s %s → %s  x-request-id=%s", method, path, resp.status_code, req_id)
        self._recent_api_calls.append({
            "method": method,
            "path": path,
            "status_code": resp.status_code,
            "request_id": req_id,
            "called_at": datetime.now(timezone.utc).isoformat(),
        })
        if len(self._recent_api_calls) > 200:
            self._recent_api_calls = self._recent_api_calls[-200:]

        # 204 No Content is a success response with no body (e.g. cancel ACK) (0297).
        if resp.status_code == 204:
            return None
        if not resp.ok:
            raise BrokerSettlementIndeterminate(
                f"AlpacaAdapter: {method} {path} returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_id(self) -> str:
        data = self._request("GET", "/v2/account")
        account_id = data["id"]
        if self._expected_account_id and account_id != self._expected_account_id:
            raise BrokerSettlementIndeterminate(
                f"AlpacaAdapter: account_id mismatch: "
                f"broker={account_id!r} expected={self._expected_account_id!r}"
            )
        # Cache the verified account ID so all fill construction has it (0298)
        self._account_id = account_id
        return account_id

    def get_broker_account(self, account_id: str) -> BrokerAccountState:
        data = self._request("GET", "/v2/account")
        return BrokerAccountState(
            account_id=data["id"],
            cash=float(data["cash"]),
            nav=float(data["portfolio_value"]),
            buying_power=float(data["buying_power"]),
        )

    def get_market_clock(self) -> dict:
        """Return {'is_open': bool, 'next_open': str, 'next_close': str} from GET /v1/clock."""
        data = self._request("GET", "/v1/clock")
        return {
            "is_open": bool(data.get("is_open", False)),
            "next_open": data.get("next_open", ""),
            "next_close": data.get("next_close", ""),
        }

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self, account_id: str) -> list[BrokerPosition]:
        rows = self._request("GET", "/v2/positions")
        return [
            BrokerPosition(
                symbol=r["symbol"],
                qty=float(r["qty"]),
                avg_cost=float(r["avg_entry_price"]),
                instrument_type="EQUITY",
                market_price=float(r["current_price"]) if r.get("current_price") else None,
                market_value=float(r["market_value"]) if r.get("market_value") else None,
            )
            for r in rows
            if r.get("asset_class") in (None, "us_equity")
        ]

    # ── Orders ────────────────────────────────────────────────────────────────

    def get_open_orders(self, account_id: str) -> list[BrokerOrder]:
        rows = self._request("GET", "/v2/orders", params={"status": "open"})
        return [self._map_order(r) for r in rows]

    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        try:
            data = self._request("GET", f"/v2/orders/{order_id}")
        except BrokerSettlementIndeterminate as exc:
            if "404" in str(exc):
                return None
            raise
        return self._map_order(data)

    def find_order_by_client_order_id(self, client_order_id: str) -> Optional[BrokerOrder]:
        # Correct Alpaca endpoint for client-order lookup (0297).
        # The prior implementation used GET /v2/orders/{id}?by=client_order_id which is wrong;
        # the documented endpoint is GET /v2/orders:by_client_order_id?client_order_id=<id>.
        try:
            data = self._request(
                "GET", "/v2/orders:by_client_order_id",
                params={"client_order_id": client_order_id},
            )
        except BrokerSettlementIndeterminate as exc:
            if "404" in str(exc):
                return None
            raise
        return self._map_order(data)

    def _map_order(self, data: dict) -> BrokerOrder:
        raw_status = data.get("status", "")
        normalized = _normalize_order_status(raw_status)  # fail closed on unknown (0300)
        return BrokerOrder(
            broker_order_id=data["id"],
            symbol=data["symbol"],
            side=data["side"].upper(),
            quantity=float(data.get("qty") or 0),
            fill_qty=float(data.get("filled_qty") or 0),
            state=normalized,
            limit_price=float(data["limit_price"]) if data.get("limit_price") else None,
            client_order_id=data.get("client_order_id"),
        )

    # ── Fills ─────────────────────────────────────────────────────────────────

    def get_fills(self, account_id: str, since: Optional[str] = None) -> list[BrokerFill]:
        fills: list[BrokerFill] = []
        # Use the specific-type endpoint /v2/account/activities/FILL to avoid
        # the plural parameter ambiguity of activity_types= (0297).
        params: dict = {"page_size": 100}
        if since:
            params["after"] = since
        while True:
            rows = self._request("GET", "/v2/account/activities/FILL", params=params)
            if not rows:
                break
            for r in rows:
                fills.append(self._map_fill(r, account_id))
            # Alpaca paginates via page_token; fewer than page_size rows means last page
            if len(rows) < 100:
                break
            params["page_token"] = rows[-1]["id"]
        return fills

    def get_fills_for_order(self, broker_order_id: str) -> list[BrokerFill]:
        # Use specific-type endpoint with same page_size+page_token pagination as get_fills() (0297, 0298, 0304)
        fills: list[BrokerFill] = []
        params: dict = {"order_id": broker_order_id, "page_size": 100}
        while True:
            rows = self._request("GET", "/v2/account/activities/FILL", params=params)
            if not rows:
                break
            for r in rows:
                fills.append(self._map_fill(r, self._account_id, broker_order_id=broker_order_id))
            if len(rows) < 100:
                break
            params["page_token"] = rows[-1]["id"]
        return fills

    def _map_fill(
        self,
        data: dict,
        account_id: Optional[str],
        broker_order_id: Optional[str] = None,
    ) -> BrokerFill:
        # Use cached _account_id as fallback so fills always carry account identity (0298, 0304)
        resolved_account_id = account_id or self._account_id
        if resolved_account_id is None:
            raise BrokerSettlementIndeterminate(
                "AlpacaAdapter._map_fill: account_id is None — call get_account_id() or "
                "pass expected_account_id at construction before fetching fills."
            )
        return BrokerFill(
            broker_fill_id=data["id"],
            broker_order_id=broker_order_id or data.get("order_id", ""),
            symbol=data["symbol"],
            side=data["side"].upper(),
            qty=float(data["qty"]),
            price=float(data["price"]),
            filled_at=data.get("transaction_time") or data.get("timestamp", ""),
            fee=0.0,  # Alpaca does not report per-fill commission in activities
            account_id=resolved_account_id,
        )

    # ── Quotes ────────────────────────────────────────────────────────────────

    def get_quote(self, symbol: str) -> Optional[BrokerQuote]:
        try:
            data = self._request(
                "GET", f"/v2/stocks/{symbol}/quotes/latest",
                base=self._data_url,
            )
        except BrokerSettlementIndeterminate:
            return None
        q = data.get("quote") or data
        return BrokerQuote(
            bid=float(q.get("bp") or q.get("bid_price") or 0),
            ask=float(q.get("ap") or q.get("ask_price") or 0),
            symbol=symbol,
            market_timestamp=q.get("t") or q.get("timestamp"),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            source="alpaca",
        )

    # ── Order mutation (0295) ─────────────────────────────────────────────────

    def submit_order(self, intent: TradeIntent, client_order_id: Optional[str] = None) -> BrokerOrderAck:
        if not self._submission_enabled:
            raise RuntimeError(
                "submission_enabled=False; set explicitly to enable paper order submission"
            )
        # Pre-flight validation (0311): reject non-equity/non-LIMIT/non-DAY/non-whole-share intents
        # before any network call. Raises ValueError (logic fault, not transient broker error).
        if intent.instrument_type != InstrumentType.EQUITY:
            raise ValueError(
                f"AlpacaAdapter only submits EQUITY orders; got instrument_type={intent.instrument_type!r}"
            )
        if intent.order_type != OrderType.LIMIT:
            raise ValueError(
                f"AlpacaAdapter only submits LIMIT orders; got order_type={intent.order_type!r}"
            )
        if intent.time_in_force != TimeInForce.DAY:
            raise ValueError(
                f"AlpacaAdapter only submits DAY orders; got time_in_force={intent.time_in_force!r}"
            )
        if intent.side not in (Side.BUY, Side.SELL):
            raise ValueError(
                f"AlpacaAdapter only submits BUY or SELL orders; got side={intent.side!r}"
            )
        qty = intent.quantity or 0
        if qty <= 0 or qty != int(qty):
            raise ValueError(
                f"AlpacaAdapter requires positive whole-share quantity; got quantity={qty!r}"
            )
        body = {
            "symbol": intent.symbol,
            "qty": str(int(intent.quantity)),
            "side": intent.side.value.lower(),
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(intent.limit_price),
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        try:
            data = self._request("POST", "/v2/orders", json=body)
        except BrokerSettlementIndeterminate as exc:
            raise BrokerSubmissionIndeterminate(
                f"AlpacaAdapter.submit_order: order POST failed — broker acceptance unknown; "
                f"restart will recover via client_order_id: {exc}"
            ) from exc
        broker_order_id = data["id"]
        raw_status = data.get("status", "")
        normalized = _normalize_order_status(raw_status)
        # Track this order ID so poll_order_events() can refresh it (0299)
        self._tracked_broker_order_ids.add(broker_order_id)
        return BrokerOrderAck(
            broker_order_id=broker_order_id,
            client_order_id=data.get("client_order_id"),
            normalized_state=normalized,
            accepted_at=data.get("submitted_at"),
            raw_status=raw_status,
        )

    def cancel_order(self, order_id: str, reason: str = "USER_REQUESTED") -> BrokerCancelAck:
        try:
            # Alpaca returns 204 No Content on success; _request() returns None for 204 (0297)
            self._request("DELETE", f"/v2/orders/{order_id}")
            accepted = True
        except BrokerSettlementIndeterminate as exc:
            if "404" in str(exc) or "422" in str(exc):
                accepted = False
            else:
                raise
        order = self.get_order(order_id)
        if order is None:
            # Both DELETE and GET returned 404 — broker has no record of this order_id.
            # Absence is not evidence of cancellation; fail closed (0303).
            raise BrokerSettlementIndeterminate(
                f"AlpacaAdapter.cancel_order: DELETE returned 404/422 and "
                f"GET /v2/orders/{order_id!r} also returned 404 — broker has no record "
                f"of this order_id; cannot confirm cancellation state."
            )
        state = order.state
        return BrokerCancelAck(
            broker_order_id=order_id,
            accepted=accepted,
            normalized_state=state,
            raw_status=state,
        )

    def poll_order_events(
        self, account_id: str, quote: Optional[BrokerQuote] = None
    ) -> list[BrokerOrderEvent]:
        """Refresh each tracked open order by its broker ID (0299).

        The prior submitted-at watermark approach (GET /v2/orders?status=all&after={ts})
        is incorrect: Alpaca's `after` parameter filters by order submission time, not by
        last state-change time. An order submitted before the watermark that later fills,
        cancels, or is rejected is excluded from the response — events are silently lost.

        This implementation:
        1. On first call: seeds _tracked_broker_order_ids from the broker's currently open
           orders so a restart recovers order tracking without DB access.
        2. Calls get_open_orders() to see which tracked orders are still open at the broker.
        3. For each tracked order not in the broker's open set, calls get_order() to fetch
           final state and emits a BrokerOrderEvent.
        4. Removes closed orders from the tracking set.

        The durable get_fills() ledger (called by sync_broker_state()) remains the canonical
        fill source. This polling path detects cancellations and rejections that fills cannot.

        Streaming (Alpaca trade updates WebSocket) is the preferred long-term replacement.
        """
        # Seed tracking set from broker on first poll (handles restart) (0299, 0301).
        # Failure leaves _poll_seeded=False so the next cycle retries — do not swallow.
        if not self._poll_seeded:
            open_orders = self.get_open_orders(account_id)
            for o in open_orders:
                self._tracked_broker_order_ids.add(o.broker_order_id)
            self._poll_seeded = True

        if not self._tracked_broker_order_ids:
            return []

        # Broker unreachability must propagate, not silently become "no events" (0301).
        open_orders = self.get_open_orders(account_id)

        broker_open_ids = {o.broker_order_id for o in open_orders}
        _ACTIONABLE = {"FILLED", "PARTIALLY_FILLED", "CANCELLED", "EXPIRED", "REJECTED"}
        events: list[BrokerOrderEvent] = []
        still_open: set[str] = set()

        for broker_order_id in list(self._tracked_broker_order_ids):
            if broker_order_id in broker_open_ids:
                still_open.add(broker_order_id)
                continue
            # Not in broker's open set — has reached a terminal state; refresh to confirm.
            # If get_order() raises, the broker confirmed the order is no longer open but
            # cannot report its terminal state — propagate rather than silently deferring (0305).
            order = self.get_order(broker_order_id)
            if order is None or order.state not in _ACTIONABLE:
                # Order not found or still in a non-terminal state; keep tracking
                still_open.add(broker_order_id)
                continue
            events.append(BrokerOrderEvent(
                event_type=order.state,
                broker_order_id=broker_order_id,
                client_order_id=order.client_order_id,
            ))

        self._tracked_broker_order_ids = still_open
        return events
