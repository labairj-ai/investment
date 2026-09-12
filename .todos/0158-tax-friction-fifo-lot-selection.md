# Limit Tax Lot Analysis to Shares Actually Being Assigned (FIFO)

- **ID:** 0158
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0157

## Problem

`_lot_tax_friction()` accumulates ST/LT gains across **all** cost lots for the ticker, regardless of how many shares the covered call covers. If you hold 300 shares with one 1-contract call, only 100 shares are assigned — but the helper evaluates tax friction on all 300, potentially tripling the stated friction and causing a wrong ROLL recommendation.

The helper should identify exactly which lots would be delivered under the broker's disposal method (FIFO is the default unless specific-ID is configured) and stop once `shares_to_assign` is exhausted. That is what "lot-specific" tax analysis actually means.

## Proposed approach

After this todo depends on 0157 (which adds `shares_to_assign` to the signature), walk lots in FIFO order (oldest `purchase_date` first) inside `_lot_tax_friction()`:

```python
remaining = shares_to_assign
for lot in sorted(lots, key=lambda l: l["purchase_date"]):
    allocated = min(float(lot["shares"]), remaining)
    gain = allocated * (assignment_price - float(lot["cost_per_share"]))
    ...
    remaining -= allocated
    if remaining <= 0:
        break
```

Compute `st_gain`, `lt_gain`, and `soonest_lt_days` only on the allocated shares. This is the canonical FIFO path; add a `lot_selection` field to `cc_policy` (default `"FIFO"`) as a hook for future specific-ID support.

## Touches

- `covered_call_rec.py` — `_lot_tax_friction()`: replace full-lot scan with FIFO walk stopping at `shares_to_assign`
- `agents/covered_call_agent.py` — `_CC_POLICY_DEFAULTS`: add `"lot_selection": "FIFO"` (no behavior change today)
- `tests/` — test: 300 shares, 1 contract, 2 oldest lots are LT → only those 100 shares evaluated

## Done when

- [ ] FIFO walk stops once `shares_to_assign` is exhausted
- [ ] Gains computed only on the allocated portion of each lot
- [ ] Test: 300-share holding, 1 contract → 100 shares evaluated, not 300
- [ ] Test: oldest lots are LT, ST lots never reached → friction = 0 (correct)
- [ ] Existing tests pass
