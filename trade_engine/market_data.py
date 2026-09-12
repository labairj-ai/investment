"""Market data retrieval: quote fetching utilities (0225).

Extracted from execution_engine to break the circular dependency where
BrokerAdapter imported from ExecutionEngine. Both execution_engine and
broker_adapter import from here. ExecutionEngine → BrokerAdapter, both → market_data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .shadow_broker import Quote


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_quote(symbol: str) -> Optional[Quote]:
    """Fetch bid/ask from yfinance; falls back to last_price when bid/ask unavailable.

    Suitable for position marking only — NOT for fill execution.
    Use _get_executable_quote() for fills.
    """
    try:
        import yfinance as yf
        retrieved_at = _now_utc().isoformat()
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        bid = float(getattr(info, "bid", None) or 0)
        ask = float(getattr(info, "ask", None) or 0)
        last = float(getattr(info, "last_price", None) or 0)
        if bid <= 0:
            bid = last
        if ask <= 0:
            ask = last
        if bid > 0 and ask > 0:
            market_ts = None
            try:
                rmt = getattr(info, "regular_market_time", None)
                if rmt:
                    market_ts = datetime.fromtimestamp(float(rmt), tz=timezone.utc).isoformat()
            except Exception:
                pass
            return Quote(
                bid=bid, ask=ask,
                timestamp=retrieved_at,
                market_timestamp=market_ts,
                retrieved_at=retrieved_at,
                source="yfinance",
            )
    except Exception:
        pass
    return None


def _get_executable_quote(symbol: str) -> Optional[Quote]:
    """Fetch a genuine bid+ask quote for fill execution.

    Returns None when either bid or ask is unavailable — fail closed.
    Unlike _get_quote(), does NOT manufacture zero-spread from last_price.
    """
    try:
        import yfinance as yf
        retrieved_at = _now_utc().isoformat()
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        bid = float(getattr(info, "bid", None) or 0)
        ask = float(getattr(info, "ask", None) or 0)
        if bid <= 0 or ask <= 0:
            return None
        market_ts = None
        try:
            rmt = getattr(info, "regular_market_time", None)
            if rmt:
                market_ts = datetime.fromtimestamp(float(rmt), tz=timezone.utc).isoformat()
        except Exception:
            pass
        return Quote(
            bid=bid, ask=ask,
            timestamp=retrieved_at,
            market_timestamp=market_ts,
            retrieved_at=retrieved_at,
            source="yfinance",
        )
    except Exception:
        pass
    return None


def _get_mark_price(symbol: str) -> Optional[float]:
    """Return mid price for position marking, with last-price fallback.

    Not suitable for fill execution.
    """
    quote = _get_quote(symbol)
    if quote:
        return (quote.bid + quote.ask) / 2.0
    return None
