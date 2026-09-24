# Surface Detailed Freshness Contributors in Brief Health

- **ID:** 0647
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0644

## Problem

When freshness degrades, `brief_health_detail` currently records only `["freshness"]`, which collapses all freshness contributors into one opaque token. The brief can then only say "freshness unavailable" rather than "Guardian status unavailable and news snapshot stale." This makes the brief less actionable and harder to triage — an operator cannot tell from the brief alone which specific subsystem is the problem.

## Proposed approach

Instead of adding the string `"freshness"` to `brief_health_detail` when `freshness.overall == DEGRADED`, enumerate the individual degraded/errored freshness entries:

```python
for key, entry in freshness.items():
    if key == "overall":
        continue
    if entry.get("status") in ("STALE", "UNAVAILABLE", "UNKNOWN", "ERROR"):
        _health_degraded.append(f"freshness.{key}:{entry['status']}")
```

This gives `brief_health_detail` entries like:
- `freshness.guardian_run:ERROR`
- `freshness.news_snapshot:STALE`
- `freshness.learning_sweep:UNAVAILABLE`

The `_enforce_brief_health()` function (0644) and any brief rendering code can then surface a specific message:
> "Portfolio assessment degraded — Guardian status unavailable and news snapshot stale."

## Touches

- `portfolio_ai.py` — `build_portfolio_brief_state()`: replace `_health_degraded.append("freshness")` with per-entry enumeration
- `agents/briefing_agent.py` — UNKNOWN-state headline may reference specific contributors from `brief_health_detail`
- `tests/test_portfolio_brief.py` — test that a stale Guardian run produces `"freshness.guardian_run:STALE"` in `brief_health_detail`

## Done when

- [ ] `brief_health_detail` contains per-entry freshness contributors (e.g. `"freshness.guardian_run:STALE"`) rather than `"freshness"`
- [ ] A test seeds a stale Guardian run and asserts the specific contributor token appears in `brief_health_detail`
- [ ] The UNKNOWN/DEGRADED headline uses the contributor list to produce a specific message (not just "freshness")
