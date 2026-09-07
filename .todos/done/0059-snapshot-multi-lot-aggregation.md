# Snapshot: Fix Multi-Lot Aggregation Bug

- **ID:** 0059
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** P0
- **Depends:** none

## Problem

`snapshot.py` builds `csv_map` using `csv_map[t] = {...}` — each row for the same ticker overwrites the prior one. If `holdings.csv` contains multiple lots for the same ticker (e.g., two ANET lots at different cost bases), the snapshot sees only the last row's shares and avg_cost. This produces materially wrong data for:

- CC eligibility check (contracts = shares // 100 — wrong share count)
- Cost-basis protection in CC strike selection
- Sell/Trim concentration and cost-basis analysis
- Critic CC veto based on shares vs contracts
- Portfolio weight calculations derived from shares

Example: 60 shares @ $110 + 70 shares @ $145 → snapshot shows 70 shares @ $145 instead of 120 shares @ $134.58.

## Proposed approach

Replace the overwrite with lot accumulation:

```python
if t in csv_map:
    existing = csv_map[t]
    total_shares = existing["shares"] + shares
    # weighted average cost basis
    weighted_cost = (
        (existing["shares"] * existing["avg_cost"]) + (shares * avg_cost)
    ) / total_shares if total_shares > 0 else 0.0
    csv_map[t] = {"shares": total_shares, "avg_cost": weighted_cost, "layer": layer}
else:
    csv_map[t] = {"shares": shares, "avg_cost": avg_cost, "layer": layer}
```

Extract this into a shared `_aggregate_lots(rows) -> dict[str, dict]` function inside `snapshot.py` so it can be called from any future code path that reads holdings.

If multiple rows for the same ticker have different `Layer` values, use the first-seen layer (they should be the same lot of the same position; log a warning if they differ).

## Touches

- `agents/snapshot.py` — replace `csv_map[t] = ...` with `_aggregate_lots` logic
- `agents/covered_call_agent.py` — may have its own local CSV parse to audit and align
- `agents/sell_trim_agent.py` — same

## Done when

- [ ] Two lots of the same ticker in holdings.csv → HoldingSnapshot has sum of shares and weighted avg_cost
- [ ] `_aggregate_lots()` helper function exists and is used by the CSV reader
- [ ] Layer conflict (different lot rows with different Layer) logs a warning
- [ ] Unit test: `_aggregate_lots([{ANET, 60, 110, L3}, {ANET, 70, 145, L3}])` → 120 shares @ $134.58
- [ ] **Backend QA:** run on optiplex with production holdings.csv; snapshot matches expected totals
- [ ] **No service regression:** investment service running; dashboard loads
