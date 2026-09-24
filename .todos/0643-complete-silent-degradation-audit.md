# Complete Silent-Degradation Audit for Brief Builder

- **ID:** 0643
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0639, 0640

## Problem

While 0638 removed silent catches from thesis, learning, and execution state, silent `except Exception: pass` blocks and silent fallbacks remain in other parts of `build_portfolio_brief_state()` — notably prior-snapshot diffing and several freshness lookups. A failed Guardian freshness lookup is currently indistinguishable from "Guardian has never run." Once `brief_health` (0640) is computed from subsystem statuses, these silent failures would be invisible to the reliability calculation.

There is also a semantic distinction that currently collapses: a subsystem that legitimately has no data (e.g., no Guardian runs ever) vs. one that had a DB error during the read. Both produce the same output today. `brief_health` needs to distinguish them to be meaningful.

## Proposed approach

- Audit every remaining `except Exception: pass` and silent-fallback pattern in `build_portfolio_brief_state()` beyond what 0638 already fixed.
- For each: determine if the subsystem is "legitimately optional" (UNAVAILABLE is valid) or "required for accuracy" (failure should be ERROR).
- Emit `"status": "UNAVAILABLE"` for legitimate absence, `"status": "ERROR"` with `"error": str(e)` for caught exceptions.
- Make sure `brief_health` (from 0640) consumes all newly explicit statuses.
- A zero `age_hours` or `None` freshness entry is only valid when `status == "UNAVAILABLE"` (never run) — a failed read must be `status == "ERROR"`.

## Touches

- `portfolio_ai.py` — remaining `except Exception: pass` blocks in `build_portfolio_brief_state()` (prior-snapshot diff, freshness lookups, others found in audit)
- `tests/test_portfolio_brief.py` — tests that simulate subsystem DB failures and assert ERROR vs UNAVAILABLE distinction

## Done when

- [ ] No `except Exception: pass` or silent-fallback remains in `build_portfolio_brief_state()` for any subsystem that feeds brief items, freshness, or counts
- [ ] Legitimate absence (`status == "UNAVAILABLE"`) is distinguishable from failed acquisition (`status == "ERROR"`) for every subsystem
- [ ] `brief_health` (0640) reflects all newly-visible ERROR statuses
- [ ] A test proves: a simulated DB failure during Guardian freshness read produces `status == "ERROR"`, not `None` / `"UNAVAILABLE"`
