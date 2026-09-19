# Independent Macro Health Watchdog (Not Coupled to Scorer)

- **ID:** 0499
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0492, 0493

## Problem

The current health snapshot and stale-run reconciliation both depend on another scoring run executing. If the scheduler itself dies, no new scoring run fires, `_reconcile_stale_runs()` never executes, no new `macro_health_snapshots` row is written, and a dead or abandoned system looks identical to a healthy idle one. The monitoring mechanism is coupled to the process it is supposed to monitor.

## Proposed approach

Add a `compute_macro_health()` function that reads from the DB and computes health state on demand — no scoring run required. Call it:
1. When the dashboard is generated (already happens regularly via cron/systemd)
2. As a standalone daily cronjob independent of the scoring schedule

The watchdog report covers:
- Latest successful scoring run age (hours since last COMPLETE/PARTIAL)
- Any STARTED run age > 60 min (with reconciliation — transition to STALE_FAILED)
- Last health snapshot age
- Last scoring coverage (scored_n / expected_n)
- Macro series freshness (from latest cached macro context or last fetch timestamp)
- Live validation status (PRE_ACCEPTANCE / ACCEPTED, from `macro_acceptance_state`)
- Time since last live acceptance run

Dashboard reads from this function at render time rather than from the latest `macro_health_snapshots` row (which only updates when scoring runs). Add `_reconcile_stale_runs()` call inside `compute_macro_health()` so reconciliation also happens at dashboard-render time, not only at scorer startup.

New systemd timer or launchd job: `macro-health-watchdog.timer` running daily at 6am, calling `venv/bin/python -c "from portfolio_ai import compute_macro_health; print(compute_macro_health())"` and writing result to `out/macro_health_latest.json`.

## Touches

- `portfolio_ai.py` — `compute_macro_health()` standalone function
- `generate_dashboard.py` — call `compute_macro_health()` at render time
- `out/macro_health_latest.json` — daily watchdog output
- Optiplex systemd or launchd timer

## Done when

- [ ] `compute_macro_health()` runs without a scoring run having executed
- [ ] Calls `_reconcile_stale_runs()` internally so reconciliation happens at render time
- [ ] Dashboard health card populated from `compute_macro_health()`, not stale snapshot
- [ ] Daily watchdog timer on optiplex writes `out/macro_health_latest.json`
- [ ] A dead scheduler (no scoring run for 8+ days) shows as WARNING in the health card
