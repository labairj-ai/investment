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
    """Fetch bid/ask from yfinance; returns last-only quote when bid/ask unavailable.

    0368: no longer synthesizes bid=ask=last. Instead, returns a Quote with
    bid=ask=0 and last filled in — callers use bid > 0 and ask > 0 to detect
    LAST_ONLY quality and avoid fake zero-spread records.
    """
    try:
        import yfinance as yf
        retrieved_at = _now_utc().isoformat()
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        bid = float(getattr(info, "bid", None) or 0)
        ask = float(getattr(info, "ask", None) or 0)
        last_raw = getattr(info, "last_price", None)
        last_price = float(last_raw) if last_raw else None

        market_ts = None
        try:
            rmt = getattr(info, "regular_market_time", None)
            if rmt:
                market_ts = datetime.fromtimestamp(float(rmt), tz=timezone.utc).isoformat()
        except Exception:
            pass

        # Only return a Quote when we have something useful (bid/ask or at least last)
        if (bid > 0 and ask > 0) or last_price:
            return Quote(
                bid=bid, ask=ask,
                timestamp=retrieved_at,
                market_timestamp=market_ts,
                retrieved_at=retrieved_at,
                source="yfinance",
                last=last_price,
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

    Not suitable for fill execution. Returns mid when bid+ask available,
    falls back to last_price (0368: _get_quote no longer synthesizes bid/ask from last).
    """
    quote = _get_quote(symbol)
    if quote:
        if quote.bid > 0 and quote.ask > 0:
            return (quote.bid + quote.ask) / 2.0
        if quote.last and quote.last > 0:
            return float(quote.last)
    return None
