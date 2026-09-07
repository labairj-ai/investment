# Snapshot: Explicit as_of Timestamps per Data Source

- **ID:** 0060
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** P0
- **Depends:** 0059

## Problem

`PortfolioSnapshot` has `date = date.today().isoformat()` and `generated_at = time.time()`, but the underlying data may be from a different day. On a Sunday, `snapshot.date` is Sunday while `price_data` is from Friday's close. An agent receiving this snapshot cannot tell whether prices are 2 hours stale or 60 hours stale — it just sees "today's date."

This matters for:
- Confidence scoring (freshness penalty should use actual data age, not wall-clock time)
- CC recommendations (Friday IV cannot be treated as Sunday-fresh)
- Macro-driven Guardian recommendations
- Any agent that checks "is this data current enough to act on?"

## Proposed approach

Add explicit per-source `as_of` fields to `PortfolioSnapshot` in `contracts.py`:

```python
@dataclass
class PortfolioSnapshot:
    date: str                    # ISO date (generated_at day)
    total_value: float
    holdings: list[HoldingSnapshot]
    layer_weights: dict[int, float]
    macro_scores: dict[str, Any]
    generated_at: float          # unix timestamp when snapshot was built
    price_as_of: str | None = None         # MAX(day) from holding_day
    portfolio_as_of: str | None = None     # MAX(day) from portfolio_day
    layer_as_of: str | None = None         # MAX(day) from layer_day
    macro_as_of: str | None = None         # last update time for macro scores
    financials_as_of: str | None = None    # MAX(period_end) across holdings
```

In `build_portfolio_snapshot()`, populate each field from the actual MAX(day) query results that are already being executed.

Confidence scoring in `confidence.py` should then use `price_as_of` for market quote freshness instead of comparing `generated_at` to wall-clock time.

Agents can include snapshot freshness in their `why_now` when data is stale (e.g., "Note: prices are as of Friday; market opens Monday.").

No breaking change — all fields have defaults of `None`.

## Touches

- `agents/contracts.py` — add 5 `as_of` fields to `PortfolioSnapshot`
- `agents/snapshot.py` — populate all `as_of` fields from MAX(day) queries
- `agents/confidence.py` — use `price_as_of` for freshness calculation where relevant
- Agent prompts (optional) — mention price_as_of when data is >1 trading day stale

## Done when

- [ ] `PortfolioSnapshot` has all 5 `as_of` fields defined with None defaults
- [ ] `build_portfolio_snapshot()` populates each field from its DB query
- [ ] `price_as_of` and `portfolio_as_of` are distinct on weekends (Friday date vs Sunday date)
- [ ] Confidence scoring uses `price_as_of` instead of `generated_at` for market quote freshness
- [ ] **Backend QA:** run on a weekend (or simulate); verify `price_as_of` = Friday, `date` = current day
- [ ] **No service regression:** all agents continue to work; snapshot is fully backward compatible
