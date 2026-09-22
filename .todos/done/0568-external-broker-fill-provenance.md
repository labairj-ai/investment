# Track and Surface External Broker Fill Provenance

- **ID:** 0568
- **Status:** done
- **Created:** 2026-09-22
- **Priority:** normal
- **Depends:** 0567

## Problem

Fills that arrive from Alpaca without engine lineage (no local order, no trade_intent, no recommendation chain) are currently ingested as correct economic facts but carry no origin label and are invisible in runner metrics. The Sep-15 SOXS fills are the concrete example: manually tagged `manual_seed` in `fill_source` as a one-off repair, but the system has no formal model for this class of activity. As a result, the runner history shows `orders=0, fills=0` while the broker dashboard shows nine fills, with no explanation of what the difference means or why it exists.

## Proposed approach

**Architecture invariant to encode:** The broker owns truth about what financially happened. The execution engine owns truth about what the agent intended and submitted. Reconciliation connects them but must never invent missing lineage — no fake trade_intents, fake orders, or fake recommendation links for external fills.

**Schema: `fills.origin` column (TEXT, DEFAULT 'UNKNOWN')**
Values:
- `ENGINE` — fill entered through intent → risk → order → broker → `apply_broker_fill()`
- `MANUAL` — seeded directly into DB outside the engine pipeline
- `TEST` — placed via test script against the broker API
- `BROKER_EXTERNAL` — broker returned a fill with no matching local order (unexpected future trade)
- `UNKNOWN` — legacy fills inserted before this field existed (backfill existing rows)

Additional fill metadata columns:
- `engine_managed` INTEGER (1 when local order + intent chain exists, 0 otherwise)
- `first_seen_at` TEXT (timestamp engine first encountered this fill_id from broker)
- `reconciled_at` TEXT (timestamp `apply_broker_fill()` last processed it)

**`cycle_runs` table: new observation columns** (do NOT change semantics of `orders_submitted` or `fills_applied` — those remain engine-pipeline counts only):
- `broker_fills_observed` — total fills returned by `get_fills()` / `poll_order_events()`
- `broker_fills_new` — count that returned `APPLIED`
- `broker_fills_duplicate` — count that returned `ALREADY_APPLIED`
- `external_fills_observed` — count with `origin != 'ENGINE'`

**`apply_broker_fill()` change:** set `origin='ENGINE'` when a matching local order exists; set `origin='BROKER_EXTERNAL'` when the fill is applied economically but no order chain was found (currently this path raises `UnknownFillError` — open question: should BROKER_EXTERNAL fills be ingested economically without an order, or should UnknownFillError remain for paper accounts and only relax for a future explicit policy flag?).

**Dashboard card (shadow tab or new broker activity section):**
```
ENGINE ACTIVITY          BROKER ACTIVITY           ECONOMIC STATE
orders_submitted: N      broker_fills_observed: N  cash:      MATCH
engine_fills:     N      external_fills:        N  SOXS qty:  MATCH
                         engine_linked_fills:   N
                         duplicate_fills:       N
```

**Policy for BROKER_EXTERNAL fills going forward:**
- Paper account: ingest economic state, flag in dashboard, do not halt
- Real-money account (future): ingest economic state, halt autonomous submissions, require acknowledgement (unexpected external activity could indicate duplicate API key, compromised credentials, or accidental test-hitting-production)

**Backfill:** migrate existing fills with `fill_source='manual_seed'` to `origin='MANUAL'`; all others with no order chain to `origin='UNKNOWN'`.

## Touches

- `agent_db.py` — `fills` table schema migration (new columns), `cycle_runs` schema migration (new columns)
- `trade_engine/execution_engine.py` — `apply_broker_fill()` origin assignment, `sync_broker_state()` and `run_execution_cycle()` metric collection
- `trade_engine/runner.py` — pass new broker-observation metrics into `_write_cycle_run()`
- `generate_dashboard.py` or `serve.py` — broker activity dashboard card
- `tests/test_trade_engine.py` — origin assignment coverage

## Done when

- [ ] `fills` table has `origin`, `engine_managed`, `first_seen_at`, `reconciled_at` columns; existing rows backfilled
- [ ] `apply_broker_fill()` sets `origin='ENGINE'` for fills with a resolved local order, `origin='BROKER_EXTERNAL'` otherwise
- [ ] `cycle_runs` has `broker_fills_observed`, `broker_fills_new`, `broker_fills_duplicate`, `external_fills_observed`; runner populates them each cycle
- [ ] `orders_submitted` and `fills_applied` semantics are unchanged (engine-pipeline only)
- [ ] Dashboard exposes ENGINE ACTIVITY and BROKER ACTIVITY as separate sections
- [ ] Sep-15 SOXS fills show `origin='MANUAL'`, `engine_managed=0` after backfill migration
- [ ] A future external Alpaca fill (no local order) is classified `BROKER_EXTERNAL`, ingested economically, and surfaced in the dashboard without halting the paper account
