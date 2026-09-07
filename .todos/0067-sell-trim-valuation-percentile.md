# Sell/Trim: Historical Valuation Percentile Instead of Absolute Thresholds

- **ID:** 0067
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** P1
- **Depends:** 0066

## Problem

The valuation component (V) of SellStrength uses absolute thresholds like "P/E > 35 = expensive." This produces misleading signals:

- A high-growth compounder trading at 40x that historically trades at 50x is not expensive — it's cheap vs its own history.
- A value trap at 18x that historically trades at 12x is actually expensive — but the absolute threshold says it's cheap.
- Different sectors have dramatically different baseline multiples; a single cutoff penalizes all growth stocks.

## Proposed approach

### 1. Compute historical valuation percentile per ticker

For each ticker, use `company_financials` to compute historical P/E (price / EPS) over the available period. Then rank the current multiple within that distribution:

```python
def _valuation_percentile(ticker: str, current_pe: float, conn) -> float | None:
    """Return percentile of current_pe within ticker's own 5-year P/E history (0–100)."""
    rows = conn.execute(
        """SELECT period_end, price_to_earnings FROM company_financials
           WHERE ticker=? AND price_to_earnings IS NOT NULL
           ORDER BY period_end DESC LIMIT 20""",  # ~5 years of quarterly data
        (ticker,)
    ).fetchall()
    if len(rows) < 4:
        return None  # insufficient history for percentile
    historical = [r["price_to_earnings"] for r in rows]
    below = sum(1 for h in historical if h < current_pe)
    return (below / len(historical)) * 100
```

### 2. Percentile-based score bands

Replace the absolute-threshold scoring with percentile bands:

| Percentile | Interpretation | V Score contribution |
|-----------|---------------|---------------------|
| < 25th | Attractive (cheap vs own history) | 0 |
| 25–50th | Fair value | 20 |
| 50–75th | Moderately elevated | 50 |
| 75–90th | Expensive | 75 |
| > 90th | Extreme (top 10% of own history) | 100 |

### 3. Fallback to absolute thresholds

When fewer than 4 historical periods are available, fall back to the existing absolute threshold scoring and flag it:

```python
if percentile is None:
    v_score = _v_score_absolute(pe, ps, ev_fcf)
    v_method = "absolute_fallback"
else:
    v_score = _v_score_from_percentile(percentile)
    v_method = f"percentile_{percentile:.0f}th"
```

Include `v_method` in the LLM prompt so the model can qualify: "ANET's forward P/E is in the 94th percentile of its 5-year history."

### 4. Secondary metrics

Apply same percentile logic to EV/FCF and P/S where available. Report all three with weights; use average percentile when multiples disagree.

## Touches

- `agents/sell_trim_agent.py` — `_score_valuation()` rewrite; add `_valuation_percentile()` helper
- `agent_db.py` — reads from `company_financials`; need `price_to_earnings` column (verify it exists)
- LLM prompt — add `v_method` and percentile value to evidence block

## Done when

- [ ] `_valuation_percentile()` computed from company_financials for tickers with ≥4 periods
- [ ] V score uses percentile bands when history is sufficient
- [ ] Absolute threshold fallback used and flagged when < 4 periods
- [ ] LLM prompt includes "94th percentile of 5-year history" phrasing when percentile available
- [ ] Unit test: ticker with P/E always at 90th percentile of own history → V score near 100
- [ ] Unit test: ticker with P/E at 10th percentile → V score near 0 regardless of absolute multiple
- [ ] **Backend QA:** run on optiplex; compare V scores before/after for held positions
- [ ] **No service regression:** SellStrength formula and action thresholds unchanged
