# Preserve MacroMeasurement Provenance Through Cache and Fix Staleness

- **ID:** 0474
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0463

## Problem

`MacroMeasurement` provenance objects (series_id, source, observation_date, retrieved_at, units, stale) are built correctly on a fresh `fetch()` call but are stripped when the result is serialised to the 30-minute JSON cache. Every subsequent cached read returns the flat numeric dict without provenance, so downstream consumers cannot determine which CPI month, which yield date, or whether any indicator is stale. Additionally, the `stale` flag on FRED indicators is hard-coded `False` rather than computed from the observation's age relative to that series' expected cadence — a daily curve series has a different freshness expectation than monthly CPI or unemployment.

## Proposed approach

- Serialise `MacroMeasurement` objects into the cache JSON (as plain dicts under the `measurements` key) so that a cache hit returns provenance-complete data, not just the flat numeric value.
- Define a per-series staleness cadence table, e.g.:
  - Daily series (T10Y2Y, T10Y3M, FEDFUNDS daily): stale if `observation_date` is > 3 business days old
  - Monthly series (CPIAUCSL, UNRATE): stale if `observation_date` is > 45 days old
- Compute `stale` dynamically at cache-read time by comparing `observation_date` to today using the appropriate cadence — not at fetch time so a cached value that ages into staleness is correctly flagged on the next read.
- Add `observation_date` and `source` to yfinance-derived measurements (VIX, TLT, GLD, UUP, ^TNX, ^IRX): use the last trading date of the downloaded history as `observation_date`, `"yfinance"` as source, and the series symbol as `series_id`.
- When deserialising from cache, reconstruct `MacroMeasurement` objects so callers always receive the same type regardless of whether data came from a fresh fetch or cache.

## Touches

- `macro_context.py` — `fetch()`, cache serialisation/deserialisation, `_fetch_fred_indicators()`, `_fetch_yf_proxies()`

## Done when

- [x] A cache hit returns `measurements` dict with fully populated `MacroMeasurement` objects (not stripped)
- [x] `stale` is computed dynamically from `observation_date` and per-series cadence, not hard-coded
- [x] Monthly CPIAUCSL observation > 45 days old is flagged `stale=True`
- [x] Daily T10Y2Y observation > 3 business days old is flagged `stale=True`
- [x] yfinance-derived measurements carry `observation_date`, `source="yfinance"`, and `series_id`
