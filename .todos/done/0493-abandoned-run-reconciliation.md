# Reconcile Abandoned STARTED Macro Scoring Runs

- **ID:** 0493
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0485

## Problem

A scoring run that starts (writes STARTED row) but then has its process crash has no opportunity to write FAILED. Those rows persist as STARTED indefinitely. The health dashboard and Learning Lab will eventually surface STARTED rows that are hours or days old as misleading "in-progress" state. Unlike FAILED (which captured run-time errors), these abandoned runs have no scored_n, no errors_json, and no final timestamp — they simply disappear from operational visibility.

## Proposed approach

Add a reconciliation step that runs at the start of each new scoring run (or as a separate scheduled task):

```python
def _reconcile_stale_runs(conn, stale_threshold_minutes=60):
    cutoff = (datetime.utcnow() - timedelta(minutes=stale_threshold_minutes)).isoformat()
    conn.execute(
        "UPDATE macro_scoring_runs SET status='STALE_FAILED', errors_json=? "
        "WHERE status='STARTED' AND run_at < ?",
        (json.dumps(["Reconciled: process likely crashed — no FAILED written"]), cutoff)
    )
    conn.commit()
```

Call `_reconcile_stale_runs()` at the top of `generate_holding_macro_scores()` before writing the new STARTED row. Threshold: 60 minutes (configurable).

Also add STALE_FAILED rows to the health report from 0492 so they are visible in the Macro Data Health card.

## Touches

- `portfolio_ai.py` — `_reconcile_stale_runs()` helper, called at start of `generate_holding_macro_scores()`
- Macro health card (from 0492) — add STALE_FAILED count

## Done when

- [ ] `_reconcile_stale_runs()` transitions STARTED rows older than threshold to STALE_FAILED
- [ ] Called automatically at the start of each new scoring run
- [ ] STALE_FAILED rows appear in health report / health card
- [ ] No STARTED row older than threshold survives in the ledger without explanation
