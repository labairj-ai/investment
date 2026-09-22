# Fill/reconciliation hardening — 0572–0574

Reviewed against `9cb2f62`; implemented on top of `5da61b8`.

## Ownership

Initialization halts if a PENDING_SUBMIT client-order lookup fails. For a new fill
without local lineage, settlement requires a successful `get_order()` response
whose broker ID, symbol, and side agree with the fill. Matching client-order
lineage is recovered and the local order advances through normal settlement.
Missing broker evidence or an engine namespace without local lineage halts
processing without applying that fill. A confirmed non-engine order can settle
as BROKER_EXTERNAL. Replay of an already persisted fill remains idempotent.

## Equity economics

`trade_engine/fill_economics.py` supplies the same pre-fill calculation to engine,
external, and shadow settlement. SELL cost basis is quantity × prior average cost;
realized P&L is proceeds less fees and basis; percentage is P&L / basis × 100.
Zero basis produces a NULL percentage, and BUYs produce NULL realized P&L.
Fees affect cash and SELL P&L, while average entry price retains the existing
fee-exclusive convention. Option cash retains its existing multiplier behavior.
Both engine and external losing Alpaca fills are tested against MAX_DAILY_LOSS.

This changes new settlement only; historical fill economics are not rewritten.

## Telemetry

Initialization observations survive reconciliation failure and partially completed
imports. Runner HALTED summaries merge those observations. Event and ledger IDs
are unioned, with a fill newly applied in either phase counted once as new.
A quarantined, unpersisted fill is observed but is not called a duplicate.
External counts come from persisted origin. Existing `fills_applied` semantics
are unchanged. Sync failures also preserve prior successful observations.

## Deterministic paper-broker canary

Run:

```sh
venv/bin/python -m pytest tests/test_fill_hardening.py -v
```

The canary uses a separate in-memory broker ledger and an isolated SQLite database.
It does not contact Alpaca or submit orders to a broker account. Starting cash is
$10,000; each step asserts exact broker/local cash, quantity, average cost, and
zero-tolerance reconciliation. Expected broker values are explicit and do not
reuse the production economics calculator.

| Step | Fee | Ending cash | Shares | Average cost | Realized P&L |
|---|---:|---:|---:|---:|---:|
| Engine BUY 10 @ 100 | 1 | 8,999 | 10 | 100 | NULL |
| Engine SELL 4 @ 80 | 1 | 9,318 | 6 | 100 | -81 |
| External BUY 4 @ 90 | 1 | 8,957 | 10 | 96 | NULL |
| External SELL 5 @ 70 | 1 | 9,306 | 5 | 96 | -131 |
| PENDING_SUBMIT recovery: BUY 1 @ 96 | 0 | 9,210 | 6 | 96 | NULL |

Every step replays its fill and proves no second economic mutation. The recovered
order must be FILLED. Additional tests cover ownership timeouts, absent broker
orders, orphaned engine client IDs, partial/full liquidation, fractional fills,
fees, zero basis, event-only delivery, initialization HALTs, and persisted runner
summaries.

Real Alpaca paper-account integration remains separately gated by the existing
integration-test credentials and submission flags. This deterministic result is
not evidence of a live Alpaca endpoint canary.
