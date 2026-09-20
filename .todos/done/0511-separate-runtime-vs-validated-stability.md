# Separate Runtime Stability from Validated Stability

- **ID:** 0511
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0510

## Problem

A new ticker never present in the accepted N=20 validation can reach `usable_for_attribution = true` through routine weekly scoring alone. `_n_samples_for_dim()` picks N=3 for `untested`, the weekly scorer runs 3 inferences, computes stddev=0.6, assigns `stable`, and marks the dimension usable. This self-certification path bypasses the formal acceptance experiment entirely.

## Proposed approach

Distinguish two stability concepts:

- **`validated_stability`**: stability class derived only from an `accepted_validation` row in `macro_dimension_stability`. Source of truth for formal attribution usability.
- **`runtime_stability`**: stability class derived from routine scoring (`runtime_sampling` rows). Used only for adaptive N decisions, never for attribution gating.

For `usable_for_attribution`:
```python
def _is_formally_usable(ticker, dim, conn):
    """Only accepted_validation rows count for formal usability."""
    row = conn.execute(
        "SELECT stability_class FROM macro_dimension_stability "
        "WHERE ticker=? AND dimension=? AND validation_run_type='accepted_validation' "
        "ORDER BY recorded_at DESC LIMIT 1",
        (ticker, dim)
    ).fetchone()
    if not row:
        return False  # untested = not usable, not backward-compat usable
    return row[0] in ("stable", "borderline")
```

For new tickers not in the accepted validation universe: `usable_for_attribution = false` until the next formal live acceptance run includes them. The adaptive N sampling still runs to produce better point estimates, but formal attribution must wait for acceptance.

Store `validated_stability` and `runtime_stability` as separate fields in the score dict:
```json
{
  "rate_sensitivity": {
    "score": 7,
    "validated_stability": "stable",
    "runtime_stability": "borderline",
    "usable_for_attribution": true
  }
}
```

## Touches

- `portfolio_ai.py` — `_is_formally_usable()`, score dict construction, `_n_samples_for_dim()` reads runtime rows
- Score dict carries both stability fields

## Done when

- [ ] `_is_formally_usable()` only reads `accepted_validation` rows; returns false for untested tickers
- [ ] New tickers are formally untested until a live acceptance run covers them
- [ ] Score dict carries both `validated_stability` and `runtime_stability`
- [ ] Adaptive N still uses `runtime_stability` for efficiency, but attribution uses `validated_stability`
