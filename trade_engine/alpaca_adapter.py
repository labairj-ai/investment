"""AlpacaAdapter: stub external broker adapter for Alpaca paper trading (0287).

This is a stub — only the constructor and paper-safety guard are implemented.
Full method implementations are left for when live paper integration begins.

Paper-only guard: if paper=True (the only supported mode) and the provided
base_url does not contain the substring "paper", construction raises at
init time so misconfiguration is caught immediately, not at order submission.
"""
from __future__ import annotations

from typing import Optional

from .broker_adapter import BrokerAdapter
from .broker_types import (
    BrokerAccountState, BrokerCancelAck, BrokerFill, BrokerOrder,
    BrokerOrderAck, BrokerOrderEvent, BrokerPosition, BrokerQuote,
)
from .models import Fill, Order, TradingAccount, TradeIntent

_PAPER_SENTINEL = "paper"
_ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"


class AlpacaAdapter(BrokerAdapter):
    """Alpaca broker adapter — paper trading only (0287).

    Construction guard: raises ValueError at init time if paper=True (the only
    supported mode) but base_url does not contain "paper". This prevents accidental
    connection to a live endpoint through misconfiguration.
    """

    requires_market_timestamp = True  # Alpaca supplies exchange observation time

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = _ALPACA_PAPER_URL,
        *,
        paper: bool = True,
    ) -> None:
        if not paper:
            raise ValueError(
                "AlpacaAdapter only supports paper=True; live trading is not yet implemented"
            )
        if _PAPER_SENTINEL not in base_url:
            raise ValueError(
                f"AlpacaAdapter: paper=True requires a paper endpoint URL "
                f"(expected URL containing {_PAPER_SENTINEL!r}); got {base_url!r}. "
                f"Set base_url to {_ALPACA_PAPER_URL!r} for paper trading."
            )
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url

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
        raise NotImplementedError("AlpacaAdapter.get_fills not yet implemented")

    def get_fills_for_order(self, broker_order_id: str) -> list[BrokerFill]:
        raise NotImplementedError("AlpacaAdapter.get_fills_for_order not yet implemented")

    def find_order_by_client_order_id(self, client_order_id: str) -> Optional[BrokerOrder]:
        raise NotImplementedError("AlpacaAdapter.find_order_by_client_order_id not yet implemented")

    def poll_order_events(
        self, account_id: str, quote: Optional[BrokerQuote] = None
    ) -> list[BrokerOrderEvent]:
        raise NotImplementedError("AlpacaAdapter.poll_order_events not yet implemented")
