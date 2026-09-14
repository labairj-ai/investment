"""AlpacaAdapter: stub external broker adapter for Alpaca paper trading (0287, 0291).

This is a stub — only the constructor and paper-safety guard are implemented.
Full method implementations are left for when live paper integration begins.

Paper-only guard (0291): construction validates that base_url uses HTTPS and has
the exact hostname paper-api.alpaca.markets. Substring checks are insufficient —
a look-alike domain such as something-paper.example.com would pass a substring
test but connect to the wrong host.
"""
from __future__ import annotations

import urllib.parse
from typing import Optional

from .broker_adapter import BrokerAdapter
from .broker_types import (
    BrokerAccountState, BrokerCancelAck, BrokerFill, BrokerOrder,
    BrokerOrderAck, BrokerOrderEvent, BrokerPosition, BrokerQuote,
)
from .models import Fill, Order, TradingAccount, TradeIntent

_ALPACA_PAPER_HOSTNAME = "paper-api.alpaca.markets"
_ALPACA_PAPER_URL = f"https://{_ALPACA_PAPER_HOSTNAME}"

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


class AlpacaAdapter(BrokerAdapter):
    """Alpaca broker adapter — paper trading only (0287, 0291).

    Construction guard (0291): raises ValueError if paper=True (the only supported
    mode) and base_url does not pass the exact-hostname allowlist check:
      - scheme must be "https"
      - hostname must be exactly "paper-api.alpaca.markets"
    Substring checks are not sufficient — look-alike domains would pass them.
    Use _allow_custom_url=True only in tests that need a non-standard URL.
    """

    requires_market_timestamp = True  # Alpaca supplies exchange observation time

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = _ALPACA_PAPER_URL,
        *,
        paper: bool = True,
        expected_account_id: Optional[str] = None,
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
        self._base_url = base_url
        self._expected_account_id = expected_account_id

    # ── BrokerAdapter ABC stubs (not yet implemented) ─────────────────────────

    def get_account_id(self) -> str:
        raise NotImplementedError("AlpacaAdapter.get_account_id not yet implemented")

    def get_broker_account(self, account_id: str) -> BrokerAccountState:
        raise NotImplementedError("AlpacaAdapter.get_broker_account not yet implemented")

    def get_positions(self, account_id: str) -> list[BrokerPosition]:
        raise NotImplementedError("AlpacaAdapter.get_positions not yet implemented")

    def get_open_orders(self, account_id: str) -> list[BrokerOrder]:
        raise NotImplementedError("AlpacaAdapter.get_open_orders not yet implemented")

    def get_quote(self, symbol: str) -> Optional[BrokerQuote]:
        raise NotImplementedError("AlpacaAdapter.get_quote not yet implemented")

    def submit_order(self, intent: TradeIntent, client_order_id: Optional[str] = None) -> BrokerOrderAck:
        raise NotImplementedError("AlpacaAdapter.submit_order not yet implemented")

    def cancel_order(self, order_id: str, reason: str = "USER_REQUESTED") -> BrokerCancelAck:
        raise NotImplementedError("AlpacaAdapter.cancel_order not yet implemented")

    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        raise NotImplementedError("AlpacaAdapter.get_order not yet implemented")

    def get_fills(self, account_id: str, since: Optional[str] = None) -> list[BrokerFill]:
        # Implement via GET /v2/account/activities?activity_type=FILL&after={since}
        raise NotImplementedError("AlpacaAdapter.get_fills not yet implemented")

    def get_fills_for_order(self, broker_order_id: str) -> list[BrokerFill]:
        raise NotImplementedError("AlpacaAdapter.get_fills_for_order not yet implemented")

    def find_order_by_client_order_id(self, client_order_id: str) -> Optional[BrokerOrder]:
        raise NotImplementedError("AlpacaAdapter.find_order_by_client_order_id not yet implemented")

    def poll_order_events(
        self, account_id: str, quote: Optional[BrokerQuote] = None
    ) -> list[BrokerOrderEvent]:
        raise NotImplementedError("AlpacaAdapter.poll_order_events not yet implemented")
