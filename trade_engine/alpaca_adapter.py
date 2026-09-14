"""AlpacaAdapter: external broker adapter for Alpaca paper trading (0287, 0291, 0294, 0295).

Paper-only guard (0291): construction validates that base_url uses HTTPS and has
the exact hostname paper-api.alpaca.markets. Substring checks are insufficient —
a look-alike domain such as something-paper.example.com would pass a substring
test but connect to the wrong host.

Read-only methods (0294): account identity, positions, open orders, fills, quote.
Order mutation (0295): submit_order, cancel_order, get_order, poll_order_events,
behind a submission_enabled=False safety gate.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import requests

from .broker_adapter import BrokerAdapter
from .broker_types import (
    BrokerAccountState, BrokerCancelAck, BrokerFill, BrokerOrder,
    BrokerOrderAck, BrokerOrderEvent, BrokerPosition, BrokerQuote,
)
from .execution_engine import BrokerSettlementIndeterminate, BrokerSubmissionIndeterminate
from .models import TradeIntent

_ALPACA_PAPER_HOSTNAME = "paper-api.alpaca.markets"
_ALPACA_PAPER_URL = f"https://{_ALPACA_PAPER_HOSTNAME}"
_ALPACA_DATA_URL = "https://data.alpaca.markets"

# Mapping from Alpaca native trade_updates event types to normalized BrokerOrderEvent
# event_type values (0290). None = informational only; no order state change required.
_ALPACA_NATIVE_TO_NORMALIZED: dict[str, str | None] = {
    "fill":           "FILLED",
    "partial_fill":   "PARTIALLY_FILLED",
    "canceled":       "CANCELLED",
    "expired":        "EXPIRED",
    "rejected":       "REJECTED",
    # Informational lifecycle notifications — adapters may safely ignore these:
    "new":            None,
    "accepted":       None,
    "pending_new":    None,
    "replaced":       None,
    "pending_cancel": None,
    "pending_replace": None,
    "held":           None,
    "done_for_day":   None,
    "suspended":      None,
}

# Map Alpaca order status strings → normalized state strings
_ALPACA_ORDER_STATUS_MAP: dict[str, str] = {
    "new":              "WORKING",
    "accepted":         "WORKING",
    "pending_new":      "WORKING",
    "partially_filled": "PARTIALLY_FILLED",
    "filled":           "FILLED",
    "canceled":         "CANCELLED",
    "expired":          "EXPIRED",
    "rejected":         "REJECTED",
    "replaced":         "CANCELLED",
    "done_for_day":     "EXPIRED",
    "suspended":        "WORKING",
    "held":             "WORKING",
}

_REQUEST_TIMEOUT = 10  # seconds


class AlpacaAdapter(BrokerAdapter):
    """Alpaca broker adapter — paper trading only (0287, 0291, 0294, 0295).

    Construction guard (0291): raises ValueError if paper=True (the only supported
    mode) and base_url does not pass the exact-hostname allowlist check:
      - scheme must be "https"
      - hostname must be exactly "paper-api.alpaca.markets"
    Substring checks are not sufficient — look-alike domains would pass them.
    Use _allow_custom_url=True only in tests that need a non-standard URL.

    Submission gate (0295): submit_order() raises RuntimeError unless
    submission_enabled=True is passed at construction time.
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
            _parsed = urllib.parse.urlparse(base_url)
            if _parsed.scheme != "https":
                raise ValueError(
                    f"AlpacaAdapter: base_url must use HTTPS; "
                    f"got scheme {_parsed.scheme!r} in {base_url!r}"
                )
            if _parsed.hostname != _ALPACA_PAPER_HOSTNAME:
                raise ValueError(
                    f"AlpacaAdapter: base_url hostname must be exactly "
                    f"{_ALPACA_PAPER_HOSTNAME!r}; got {_parsed.hostname!r} in {base_url!r}. "
                    f"Set base_url to {_ALPACA_PAPER_URL!r} for paper trading."
                )
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._data_url = data_url.rstrip("/")
        self._expected_account_id = expected_account_id
        self._submission_enabled = submission_enabled
        self._last_poll_ts: Optional[str] = datetime.now(timezone.utc).isoformat()

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
    ) -> dict | list:
        url = f"{base or self._base_url}{path}"
        try:
            resp = requests.request(
                method, url,
                headers=self._auth_headers,
                params=params,
                json=json,
                timeout=_REQUEST_TIMEOUT,
            )
        except (requests.exceptions.Timeout, OSError) as exc:
            raise BrokerSettlementIndeterminate(
                f"AlpacaAdapter: {method} {path} timed out: {exc}"
            ) from exc
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
        return account_id

    def get_broker_account(self, account_id: str) -> BrokerAccountState:
        data = self._request("GET", "/v2/account")
        return BrokerAccountState(
            account_id=data["id"],
            cash=float(data["cash"]),
            nav=float(data["portfolio_value"]),
            buying_power=float(data["buying_power"]),
        )

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
        try:
            data = self._request(
                "GET", f"/v2/orders/{client_order_id}",
                params={"by": "client_order_id"},
            )
        except BrokerSettlementIndeterminate as exc:
            if "404" in str(exc):
                return None
            raise
        return self._map_order(data)

    def _map_order(self, data: dict) -> BrokerOrder:
        raw_status = data.get("status", "")
        normalized = _ALPACA_ORDER_STATUS_MAP.get(raw_status, "WORKING")
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
        params: dict = {"activity_type": "FILL", "page_size": 100}
        if since:
            params["after"] = since
        while True:
            rows = self._request("GET", "/v2/account/activities", params=params)
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
        rows = self._request(
            "GET", "/v2/account/activities",
            params={"activity_type": "FILL", "order_id": broker_order_id},
        )
        return [self._map_fill(r, None, broker_order_id=broker_order_id) for r in rows]

    def _map_fill(
        self,
        data: dict,
        account_id: Optional[str],
        broker_order_id: Optional[str] = None,
    ) -> BrokerFill:
        return BrokerFill(
            broker_fill_id=data["id"],
            broker_order_id=broker_order_id or data.get("order_id", ""),
            symbol=data["symbol"],
            side=data["side"].upper(),
            qty=float(data["qty"]),
            price=float(data["price"]),
            filled_at=data.get("transaction_time") or data.get("timestamp", ""),
            fee=0.0,  # Alpaca does not report per-fill commission in activities
            account_id=account_id,
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
        raw_status = data.get("status", "")
        normalized = _ALPACA_ORDER_STATUS_MAP.get(raw_status, "WORKING")
        return BrokerOrderAck(
            broker_order_id=data["id"],
            client_order_id=data.get("client_order_id"),
            normalized_state=normalized,
            accepted_at=data.get("submitted_at"),
            raw_status=raw_status,
        )

    def cancel_order(self, order_id: str, reason: str = "USER_REQUESTED") -> BrokerCancelAck:
        try:
            self._request("DELETE", f"/v2/orders/{order_id}")
            accepted = True
        except BrokerSettlementIndeterminate as exc:
            if "404" in str(exc) or "422" in str(exc):
                accepted = False
            else:
                raise
        order = self.get_order(order_id)
        state = order.state if order else "CANCELLED"
        return BrokerCancelAck(
            broker_order_id=order_id,
            accepted=accepted,
            normalized_state=state,
            raw_status=state,
        )

    def poll_order_events(
        self, account_id: str, quote: Optional[BrokerQuote] = None
    ) -> list[BrokerOrderEvent]:
        """Poll for order state changes since last call via GET /v2/orders?status=all."""
        since = self._last_poll_ts
        self._last_poll_ts = datetime.now(timezone.utc).isoformat()
        params: dict = {"status": "all", "limit": 100}
        if since:
            params["after"] = since
        try:
            rows = self._request("GET", "/v2/orders", params=params)
        except BrokerSettlementIndeterminate:
            return []
        # Emit events only for actionable terminal states; WORKING states are not events
        _ACTIONABLE = {"FILLED", "PARTIALLY_FILLED", "CANCELLED", "EXPIRED", "REJECTED"}
        events: list[BrokerOrderEvent] = []
        for r in rows:
            raw = r.get("status", "")
            normalized = _ALPACA_ORDER_STATUS_MAP.get(raw)
            if normalized not in _ACTIONABLE:
                continue
            events.append(BrokerOrderEvent(
                event_type=normalized,
                broker_order_id=r["id"],
                client_order_id=r.get("client_order_id"),
            ))
        return events
