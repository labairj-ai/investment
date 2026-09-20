# Quote Provenance V2: Genuine Last Trade Separate from Mid

- **ID:** 0363
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0356

## Problem

In `_fetch_quote_fields()` (intent_builder.py), `decision_last` is populated as:

```python
mid = (quote.bid + quote.ask) / 2.0
return {
    "decision_last": mid,   # ← this is midpoint, not last trade
    "decision_mid": mid,    # ← also midpoint
    ...
}
```

Two columns carry the same value with different semantic labels. When execution-learning analysis asks "fill vs last trade" or "market movement after decision", `decision_last` will give wrong answers.

The deeper issue is a poorly-defined contract for what the quote object provides. yfinance `fast_info.last_price` is available and represents the last traded price, which is semantically distinct from the bid/ask midpoint.

## Proposed approach

### Define the quote contract explicitly

The quote struct should distinguish:

| Field | Semantic | Source |
|---|---|---|
| `decision_bid` | best bid at snapshot time | yfinance |
| `decision_ask` | best ask at snapshot time | yfinance |
| `decision_mid` | (bid + ask) / 2 | computed |
| `decision_last` | last traded price | yfinance `fast_info.last_price` |
| `decision_spread_bps` | (ask − bid) / mid × 10000 | computed |
| `quote_timestamp` | when market data was captured | datetime.now(UTC) |
| `price_source` | "yfinance_live" / "payload" / etc. | string constant |

If the source does not provide a genuine last trade price, leave `decision_last = NULL` rather than populating it with midpoint.

### `_market_data._get_quote()` changes

The `Quote` namedtuple should gain a `last` field:

```python
Quote = namedtuple("Quote", ["bid", "ask", "last", "timestamp"])
```

Populated from `yfinance.Ticker(ticker).fast_info.last_price`. If unavailable, set `last=None`.

### `_fetch_quote_fields()` changes

```python
return {
    "decision_bid": quote.bid,
    "decision_ask": quote.ask,
    "decision_mid": mid,
    "decision_last": quote.last,      # NULL if genuinely unavailable
    "decision_spread_bps": round(spread_bps, 2) if spread_bps else None,
    "quote_timestamp": quote.timestamp,  # market data timestamp from exchange
    "price_source": "yfinance_live",
}
```

On fallback to payload:
```python
return {
    "decision_bid": None,
    "decision_ask": None,
    "decision_mid": None,
    "decision_last": fallback_price,   # payload price is a last-known price
    ...
    "price_source": "payload",
}
```

### Optionally: add `retrieved_at`

A separate `retrieved_at TEXT` column (wall-clock time of the API call) is useful for quote-staleness analysis. `quote_timestamp` captures the market-data timestamp; `retrieved_at` captures when the system fetched it. These differ when markets are closed and yfinance returns a stale last trade.

## Touches

- `trade_engine/market_data.py` — add `last` field to `Quote` namedtuple; populate from `fast_info.last_price`
- `trade_engine/intent_builder.py` — `_fetch_quote_fields()` sets `decision_last = quote.last` (not mid); payload fallback sets `decision_last = fallback_price`
- `agent_db.py` — optionally add `retrieved_at TEXT` column migration
- `trade_engine/models.py` — `TradeIntent.decision_last` docstring updated; `to_db_dict()` / `from_db_row()` unchanged
- `tests/test_trade_engine.py` — `TestRealQuoteSnapshotAtIntent0356`: add test asserting `decision_last != decision_mid` when last trade differs from mid; add test asserting `decision_last IS NULL` when only bid/ask available

## Done when

- [ ] `decision_last` stores genuine last trade price (not mid)
- [ ] `decision_last = NULL` when source cannot provide a real last trade
- [ ] `decision_mid` is the only field storing midpoint
- [ ] `Quote` namedtuple has distinct `last` field
- [ ] Test: mock quote with bid=99, ask=101, last=100.5 → `decision_mid=100.0`, `decision_last=100.5`
- [ ] Test: mock quote with bid/ask but no last → `decision_last IS NULL`
- [ ] `python -m pytest tests/` passes with no regressions
