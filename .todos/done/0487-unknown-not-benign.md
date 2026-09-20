# Treat Missing Regime Data as UNKNOWN, Not Benign

- **ID:** 0487
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0477

## Problem

`_compute_regime()` and `compute_regime_stress()` use `(value or 0)` / default-to-zero patterns throughout, so unavailable data silently becomes "stable" or "benign." Missing UUP → dollar classified stable; missing VIX → benign; missing geo signal → stress=0 (perfectly benign). This is the opposite of the fail-closed philosophy used in the ledger and Learning Lab. Additionally, staleness is still mostly hard-coded (stale=False set manually) rather than computed from observation date and per-series release cadence.

## Proposed approach

- Replace `(value or 0)` defaults with explicit `None` propagation. Introduce a sentinel string `"UNKNOWN"` for regime classification fields when data is absent.
- In `compute_regime_stress()`, return `None` (not `0`) for any dimension where the underlying data is missing or stale; propagate `None` through `compute_regime_adjusted_risk()` rather than treating it as zero risk.
- Split staleness into per-series cadence: daily (Treasury yields, VIX) ≤ 3 days; weekly (UUP) ≤ 7 days; monthly (CPI, unemployment) ≤ 45 days. Compute `stale` dynamically from `observation_date` + cadence, not as a hard-coded literal.
- Remove the `geopolitical_stress = 0` default; leave it `None` until a real signal exists.

## Touches

- `macro_context.py` — `_compute_regime()`, `_is_stale()`, `_SERIES_CADENCE_DAYS`
- `portfolio_ai.py` — `compute_regime_stress()`, `compute_regime_adjusted_risk()`

## Done when

- [ ] Missing UUP data produces `dollar: "UNKNOWN"` regime classification, not `"stable"`
- [ ] Missing VIX produces `volatility: "UNKNOWN"`, not a benign level
- [ ] `compute_regime_stress()` returns `None` per dimension when data absent; no `or 0` defaults
- [ ] `stale` computed from observation_date + per-series cadence, not hard-coded False
- [ ] Geopolitical stress is `None` rather than `0` when no signal is available
