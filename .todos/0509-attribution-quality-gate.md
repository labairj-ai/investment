# Attribution Quality Gate: Engine Acceptance + Per-Dimension Usability

- **ID:** 0509
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0505, 0506

## Problem

`macro_attribution.py` currently filters for `macro_validation_status=ACCEPTED` episodes, but then buckets raw structural values (rate_sensitivity, dollar_sensitivity, etc.) without checking whether each dimension is usable for attribution. After 0505, an accepted engine could still feed known-noisy geopolitical or dollar scores from foreign companies into formal analysis. Engine acceptance and dimension-level feature quality are separate gates.

## Proposed approach

Add a two-gate filter in attribution analysis:

**Gate 1 — Episode level** (already exists from 0497):
- `macro_validation_status == "ACCEPTED"`

**Gate 2 — Dimension level** (new, from 0506):
- `usable_for_attribution == true` for the specific dimension being bucketed

In `macro_attribution.py`, for each dimension analysis:
```python
# Rate sensitivity analysis — only use episodes where rate dim is usable
rate_episodes = [
    e for e in accepted_episodes
    if e["macro"].get("rate_usable_for_attribution") is True
]
# Geopolitical analysis — may have far fewer usable episodes initially
geo_episodes = [
    e for e in accepted_episodes
    if e["macro"].get("geo_usable_for_attribution") is True
]
```

Report per-dimension N separately so the analyst knows how many episodes actually contributed to each bucket analysis. A dimension with N < 20 usable episodes should be flagged as "insufficient data for attribution" rather than producing potentially misleading bucket statistics.

Unsupported and unstable dimensions remain visible in the diagnostic output (with `--include-pre-acceptance` or `--show-all-dims`) but are excluded from the formal ACCEPTED attribution tables.

## Touches

- `scripts/macro_attribution.py` — per-dimension usability filter, per-dimension N reporting
- Requires 0506 to populate `usable_for_attribution` per dimension in episode snapshots

## Done when

- [ ] Attribution buckets filtered on per-dimension `usable_for_attribution=true`
- [ ] Per-dimension N reported in output (not just total episode N)
- [ ] Dimensions with < 20 usable episodes flagged as "insufficient data"
- [ ] Unsupported/unstable dimensions visible in diagnostic mode but excluded from formal tables
- [ ] ITOCF/MITSF geopolitical_risk excluded from geo attribution until 0508 stabilises it
