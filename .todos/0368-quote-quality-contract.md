# Separate Genuine Bid/Ask from Last-Price Fallback in Quote Contract

- **ID:** 0368
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0363

## Problem

`_get_quote()` in `market_data.py` manufactures `bid` and `ask` from `last`
when the real bid or ask is unavailable:

```python
if bid is None:
    bid = last
if ask is None:
    ask = last
```

`_fetch_quote_fields()` then treats these as genuine bid/ask values, computes
a midpoint, and records a zero spread (`decision_spread_bps = 0`). The intent
row therefore shows `decision_bid = $100`, `decision_ask = $100`,
`decision_mid = $100`, `decision_spread_bps = 0` — all derived from a single
last-trade price — indistinguishable from a real tight quote.

This is the execution-analysis analog of 0363: 0363 fixed `decision_last` (no
longer populated with mid), but the opposite contamination still exists — a
synthetic bid/ask built from last. The execution path already solves this
correctly: `_get_executable_quote()` refuses to manufacture bid/ask and fails
closed. The decision snapshot should apply the same semantics.

Additionally, `quote_timestamp` currently stores retrieval wall-clock time, not
the exchange timestamp for the last trade. These are different when markets are
closed, and the distinction matters for staleness analysis.

## Proposed approach

### Quote quality tiers

```python
class QuoteQuality(str, Enum):
    BID_ASK      = "BID_ASK"       # genuine bid and ask both present
    LAST_ONLY    = "LAST_ONLY"     # only last trade; bid/ask unavailable
    PAYLOAD_FALLBACK = "PAYLOAD_FALLBACK"  # using payload price, no live quote
```

### `_get_quote()` changes

Do NOT synthesize bid/ask from last. Return quality alongside the fields:

```python
Quote = namedtuple("Quote", ["bid", "ask", "last", "market_timestamp", "retrieved_at", "quality"])
```

- `bid`, `ask` = `None` when genuinely unavailable (not replaced by `last`)
- `market_timestamp` = exchange timestamp of the last trade (from yfinance)
- `retrieved_at` = `datetime.now(UTC)` at the moment of the API call
- `quality` = `BID_ASK` if both bid and ask are real values; `LAST_ONLY` otherwise

### `_fetch_quote_fields()` changes

```python
return {
    "decision_bid":         quote.bid,          # NULL when not genuine
    "decision_ask":         quote.ask,          # NULL when not genuine
    "decision_mid":         mid if quote.bid and quote.ask else None,
    "decision_last":        quote.last,
    "decision_spread_bps":  spread_bps if mid else None,
    "decision_market_price": mid or quote.last,  # best available price for sizing
    "quote_quality":        quote.quality.value,
    "market_timestamp":     quote.market_timestamp,
    "quote_timestamp":      quote.retrieved_at,  # keep col name; semantics now = retrieval time
}
```

On payload fallback path:
```python
return {
    "decision_bid": None, "decision_ask": None, "decision_mid": None,
    "decision_last": fallback_price,
    "decision_market_price": fallback_price,
    "quote_quality": QuoteQuality.PAYLOAD_FALLBACK.value,
    ...
}
```

### Schema additions

In `agent_db.py` `_new_cols`:
```python
("trade_intents", "quote_quality",        "TEXT"),
("trade_intents", "market_timestamp",     "TEXT"),
("trade_intents", "decision_market_price","REAL"),
```

`quote_quality` allows downstream analysis to filter by data quality tier.
`decision_market_price` is the canonical "price we used for sizing" regardless
of which tier provided it.

## Touches

- `trade_engine/market_data.py` — `Quote` namedtuple gains `market_timestamp`, `retrieved_at`, `quality`; `_get_quote()` does not synthesize bid/ask from last
- `trade_engine/intent_builder.py` — `_fetch_quote_fields()` sets NULL bid/ask when not genuine; adds `quote_quality`, `market_timestamp`, `decision_market_price`
- `agent_db.py` — `_new_cols` for `quote_quality`, `market_timestamp`, `decision_market_price`
- `trade_engine/models.py` — `TradeIntent` gains the three new fields
- `tests/test_trade_engine.py` — test that unavailable bid/ask produces NULL mid and NULL spread; test that quote_quality=LAST_ONLY when only last present; test that BID_ASK quality requires both genuine values

## Done when

- [ ] `_get_quote()` never sets `bid` or `ask` from `last`
- [ ] `decision_bid`, `decision_ask`, `decision_mid`, `decision_spread_bps` are all NULL when only `last` is available
- [ ] `quote_quality` persisted on every intent row (`BID_ASK` / `LAST_ONLY` / `PAYLOAD_FALLBACK`)
- [ ] `market_timestamp` (exchange time) and `quote_timestamp` (retrieval time) are distinct fields
- [ ] `decision_market_price` = best available price for sizing regardless of tier
- [ ] Test: mock with last=100, no bid/ask → decision_mid=NULL, spread=NULL, quality=LAST_ONLY
- [ ] Test: mock with bid=99, ask=101, last=100 → decision_mid=100, spread=200bps, quality=BID_ASK
- [ ] `python -m pytest tests/` passes with no regressions
