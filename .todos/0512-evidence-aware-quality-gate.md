# Evidence-Aware Quality Gate: Both Stability AND Evidence Required

- **ID:** 0512
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0511

## Problem

`_usable_for_attribution` currently decides solely from stability — it ignores `evidence_quality_rate`, `evidence_quality_dollar`, etc. A dimension with `evidence_quality = "none"` can be marked usable if it happens to produce consistent (but groundless) scores. Example: `geopolitical_risk` with no evidence, N=3 all scoring 4 → stddev=0 → stable → `usable_for_attribution=true`. This is the opposite of what the evidence contract was designed to prevent.

## Proposed approach

Update `_usable_for_attribution` to require BOTH:
1. `validated_stability` acceptable (stable or borderline, from accepted_validation row)
2. `evidence_quality` for that dimension meets a minimum threshold

Per-dimension evidence minimum:
- `rate_sensitivity`: `evidence_quality_rate` ∈ {full, partial} → eligible
- `dollar_sensitivity`: `evidence_quality_dollar` ∈ {full, partial} → eligible; "none" (missing foreign_rev_pct) → false
- `inflation_hedge`: `evidence_quality_inflation` ∈ {full, partial} → eligible
- `geopolitical_risk`: `evidence_quality_geo` ∈ {full, partial} → eligible; "none" or "limited" → false until 0508 data exists

`unsupported` is always false regardless of stability.
`none` is always false regardless of stability.

```python
_EV_MIN = {
    "rate_sensitivity":  {"full", "partial"},
    "dollar_sensitivity": {"full", "partial"},
    "inflation_hedge":   {"full", "partial"},
    "geopolitical_risk": {"full"},  # stricter — geo "partial" is too thin until 0508
}

def _usable_for_attribution(ticker, dim, evidence_quality, conn):
    if evidence_quality not in _EV_MIN.get(dim, set()):
        return False
    return _is_formally_usable(ticker, dim, conn)
```

## Touches

- `portfolio_ai.py` — `_usable_for_attribution()` signature and implementation
- Score dict construction — pass evidence_quality per dim into the function

## Done when

- [ ] `_usable_for_attribution` takes both stability and evidence quality as inputs
- [ ] `evidence_quality = "none"` or `"unsupported"` → false regardless of stability
- [ ] `geopolitical_risk` requires `"full"` evidence quality (stricter than other dims)
- [ ] Synthetic test: geo with none evidence + stable → false
- [ ] Synthetic test: rate with partial evidence + stable → true
