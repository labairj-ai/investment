# Geo Quality Contract: Confidence + Freshness + Provenance Before Enabling Geo Attribution

- **ID:** 0522
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0519, 0521

## Problem

`evidence_quality_geo` is currently set to `"full"` in the score blob for tickers with geo evidence, regardless of the underlying confidence level, data freshness, or provenance completeness of the `company_geo_profile` row. A manually seeded row with `confidence = "medium"` and `source_date = "2026-09"` is treated identically to a row backed by a verified filing. Since geo attribution is currently disabled at the `macro_attribution.py` level, this is latent — but the gate will never be safe to open if the quality signal is meaningless.

Additionally, `_is_formally_usable()` (after 0519) will correctly tie usability to the active acceptance record, but geo usability also depends on whether the geo evidence itself meets a minimum quality bar, not just whether the ticker was in the validation universe.

## Proposed approach

**Derive `evidence_quality_geo` from `company_geo_profile` fields**, not as a hard-coded `"full"`:

```python
def _geo_evidence_quality(ticker, conn):
    row = conn.execute(
        "SELECT confidence, source_date, data_source, primary_country FROM company_geo_profile WHERE ticker=?",
        (ticker,)
    ).fetchone()
    if not row or not row[3]:  # no geo record or no country
        return "none"
    confidence, source_date, data_source, _ = row
    # Freshness: source_date must be within 18 months
    if source_date:
        try:
            yr, mo = int(source_date[:4]), int(source_date[5:7]) if len(source_date) >= 7 else 1
            import datetime
            age_months = (datetime.date.today().year - yr) * 12 + (datetime.date.today().month - mo)
            if age_months > 18:
                return "partial"  # stale — downgrade
        except (ValueError, TypeError):
            return "partial"  # unparseable date
    if confidence in ("high",):
        return "full"
    elif confidence in ("medium",):
        return "partial"
    else:
        return "none"
```

**Geo attribution gate**: `evidence_quality_geo = "full"` is required for geo usability (per `_EV_MIN_FOR_USABILITY`). This means:
- `confidence = "medium"` → `"partial"` → not usable for attribution
- `confidence = "high"` + fresh source_date → `"full"` → usable

This means geo attribution will remain effectively disabled until at least one ticker has `confidence = "high"` with a sourced date — which is the correct posture. Document this threshold in `macro_attribution.py` as a comment so future operators know what is required to enable geo.

## Touches

- `portfolio_ai.py` — new `_geo_evidence_quality()` helper; called when building per-dim evidence in `generate_holding_macro_scores()`
- `scripts/macro_attribution.py` — comment documenting geo enable condition (confidence=high, fresh source_date)

## Done when

- [ ] `evidence_quality_geo` derived from `confidence` + `source_date` + `data_source`, not hard-coded
- [ ] `confidence="medium"` produces `"partial"` (not usable under current gate)
- [ ] `confidence="high"` + source_date ≤ 18 months old produces `"full"` (usable)
- [ ] Stale or unparseable `source_date` downgrades quality to `"partial"`
- [ ] Attribution script comments document that geo requires confidence=high + fresh source_date
