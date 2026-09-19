# Fix Yield-Curve Mismatch and Add Macro Measurement Provenance

- **ID:** 0463
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** none

## Problem

`spread_bps` is populated from FRED series T10Y2Y (10Y–2Y spread) but the dashboard labels it "10Y–3M Spread". The Yahoo fallback calculates ^TNX–^IRX (≈10Y–3M), so the field's definition silently changes depending on which data source succeeded. On any given day the two spreads can differ by 60+ bps — a material mismatch for a field used as a macro signal. Beyond the yield curve, individual macro indicators don't carry their own observation date, release date, source, units, or freshness, making it impossible to know which month's CPI or which day's VIX is embedded in a snapshot labeled only "today."

## Proposed approach

- Split yield-curve into two independent fields: `yield_curve_10y2y_bps` (source: FRED T10Y2Y) and `yield_curve_10y3m_bps` (source: FRED T10Y3M). Never substitute one for the other.
- Define a `MacroMeasurement` structure (dataclass or TypedDict) with fields: `value`, `series_id`, `source`, `observation_date`, `retrieved_at`, `units`, `stale`.
- Wrap every macro indicator (VIX, 10Y yield, CPI, Fed Funds, etc.) in this structure at fetch time.
- Update all consumers (scoring prompts, dashboard, composite calculation) to read from the typed structure rather than bare floats.
- Add a stale threshold per series (e.g., CPI > 45 days old → stale) and surface staleness in the dashboard.

## Touches

- `macro_context.py` (or equivalent macro fetch module)
- Dashboard generation / macro rendering
- Macro scoring prompt builder
- DB schema if macro snapshots are persisted

## Done when

- [ ] `spread_bps` field removed or renamed; `yield_curve_10y2y_bps` and `yield_curve_10y3m_bps` stored independently with distinct sources
- [ ] Dashboard label matches the underlying series actually fetched
- [ ] Every persisted macro indicator carries `series_id`, `source`, `observation_date`, `retrieved_at`, `units`, and `stale`
- [ ] No macro snapshot can mix observation dates without each indicator's own date being visible
