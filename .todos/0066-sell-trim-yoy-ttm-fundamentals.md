# Sell/Trim: YoY and TTM Fundamental Comparisons

- **ID:** 0066
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** P1
- **Depends:** none

## Problem

The Sell/Trim agent's fundamental deterioration score (F component) currently compares adjacent/arbitrary quarters. For businesses with seasonal revenue patterns, Q2 vs Q1 or Q4 vs Q3 comparisons produce misleading results — a retailer's Q1 always looks terrible next to Q4. This creates false deterioration signals and potentially false TRIM/EXIT recommendations.

## Proposed approach

### 1. YoY comparisons for period-over-period metrics

Replace adjacent-quarter comparisons with same-quarter year-over-year:

```python
# Instead of: revenue_q[-1] vs revenue_q[-2]
# Use: revenue_q[-1] vs revenue_q[-5]  (same quarter last year)
def _yoy_growth(values: list[float], periods: list[str]) -> float | None:
    """Return YoY growth rate for the most recent quarter vs same quarter prior year."""
    # Find most recent quarter and same quarter from ~4 periods ago
    ...
```

Apply YoY to: revenue, EPS, gross margin, operating income, FCF.

### 2. TTM (trailing twelve months) for smoothed metrics

For metrics where TTM is more meaningful than any single quarter:

```python
def _ttm(values: list[float]) -> float | None:
    """Sum of last 4 quarters."""
    if len(values) >= 4:
        return sum(values[-4:])
    return None

# Compare: TTM revenue (last 4Q) vs prior TTM revenue (Q[-4] to Q[-8])
ttm_growth = (_ttm(revenue_recent) - _ttm(revenue_prior)) / abs(_ttm(revenue_prior))
```

Apply TTM to: revenue growth, FCF.

### 3. Fallback behavior

If fewer than 5 periods are available (can't do YoY), fall back to QoQ and flag the comparison type in the score metadata:

```python
comparison_type = "YoY" if len(revenue) >= 5 else "QoQ_fallback"
```

Include `comparison_type` in the LLM prompt context so the model can qualify its rationale ("based on YoY comparison" vs "limited history, QoQ fallback used").

### 4. Affected score components

Only the F (Fundamental Deterioration) component changes. T, V, P, O components are unchanged.

## Touches

- `agents/sell_trim_agent.py` — rewrite fundamental comparison helpers
- `agent_db.py` — no schema changes; reads from existing `company_financials` table
- LLM prompt in sell_trim_agent — add `comparison_type` to evidence block

## Done when

- [ ] Revenue growth uses YoY when ≥5 periods available
- [ ] EPS growth uses YoY when ≥5 periods available
- [ ] TTM revenue computed and compared to prior TTM
- [ ] QoQ fallback used when history < 5 periods; flagged in prompt context
- [ ] Unit test: same-ticker data with seasonal pattern → YoY score differs materially from QoQ score in correct direction
- [ ] **Backend QA:** run sell_trim on optiplex; verify F-component rationale mentions YoY in LLM output
- [ ] **No service regression:** SellStrength range and action thresholds unchanged
