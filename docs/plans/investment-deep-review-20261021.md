# Investment codebase bug review — October 21, 2026

Historical findings: all 15 are now implemented locally. See the [implementation and validation receipt](investment-backlog-implementation-20261021.md). The original reproduction script documents the defects and intentionally asserts their prior behavior; use the regression suites for fixed-code acceptance.

## Results and scope

**15 actionable findings, backed by 17 reproduced scenarios.** Findings describe the current local working tree, including the preceding review fixes. This review did not change project source, production data, or broker state.

Repository-wide structural scan: 198 Python files, 119,910 lines, including tests and legacy code. All parsed successfully; no duplicate function/method definitions were found. Targeted logic review covered portfolio writes and snapshots, HTTP handlers, trade sizing, risk and execution, reconciliation and fills, Advisor context/policy, covered-call policies and evidence, learning outcomes and virtual books, news ingestion/state, financial data, macro provenance, scheduling, and backups. Structural scanning is not an exhaustive correctness proof; untouched branches and live integrations can contain further bugs.

Existing relevant tests: **570 passed, 2 failed** across trade engine, snapshots, outcome labeling, news intelligence, financials, dependencies, MTM prices, and portfolio brief. The two failures are the previously reproduced date-sensitive portfolio-brief fixtures, not new failures introduced by this review. Their fixed September timestamps now fall outside a 30-day query window.

Evidence: [reproduction script](../evidence/investment-deep-review-20261021/reproduce.py), [machine-readable results](../evidence/investment-deep-review-20261021/results.json), [validation receipt](../evidence/investment-deep-review-20261021/validation.json).

Reproduce from the project directory:

```sh
venv/bin/python docs/evidence/investment-deep-review-20261021/reproduce.py
```

The script extracts selected handlers with Python AST rather than importing `serve.py`, whose top-level code initializes tables and starts a server. It executes those handler bodies against temporary SQLite databases and CSVs. Risk reproductions invoke the real persisted `evaluate()` function with the repository's in-memory test schema. Provider data is stubbed; no broker calls occur. The concurrent-sell test uses a barrier after both allocations to deterministically expose a valid interleaving.

## Findings

### 1. [P1] Approved theses are ignored by policy and invalidation readers

Locations: [approval writer](../../agent_db.py:2665), [CC policy reader](../../agents/covered_call_agent.py:137), [dashboard management reader](../../covered_call_rec.py:1625), [dependency reader](../../agents/dependency_checker.py:45), [policy hash reader](../../agent_db.py:2208), [thesis version hash](../../agent_db.py:1719).

`approve_thesis()` writes `status='ACTIVE'`; these readers query `status='active'` on an ordinary case-sensitive TEXT column. They miss the approved record and silently use defaults or an empty version map. Reproduction approved a thesis with `strategy='NONE'` and assignment forbidden: the CC reader returned `INCOME` and assignment allowed; dependency versions were `{}`. Policy changes also fail to change relevant invalidation hashes.

Fix direction: use one canonical status representation in writers, migrations, and readers. Test an actual approval followed by policy loading and dependency/hash invalidation, rather than seeding lowercase fixtures.

### 2. [P1] Concurrent sells can oversell inventory and corrupt the ledger

Location: [sell handler](../../serve.py:2784).

Lot reads and FIFO allocation happen before a write transaction acquires the SQLite writer lock. Two HTTP threads can both allocate the same shares, then sequentially persist stale allocations. Reproduction started with 100 shares and submitted two concurrent 70-share sales: both succeeded, sales totaled 140, and remaining inventory was incorrectly 30.

Fix direction: acquire `BEGIN IMMEDIATE` before reading inventory; keep allocation and mutation in that transaction. Serialize/reconcile the CSV projection as well.

### 3. [P1] Undoing an earlier sale restores shares that are still sold

Location: [undo recreation](../../serve.py:2918).

If a later sale has exhausted a lot, undoing an earlier partial sale recreates the lot with the earlier allocation's `original_shares`, not the shares being undone. Reproduction: buy 100, sell 40, sell 60, undo the 40-share sale. Inventory becomes **100**, although the other 60-share sale remains recorded and inventory should be **40**.

Fix direction: restore only the undone allocation's quantity; validate/replay dependent sale allocations where needed.

### 4. [P1] Covered-call checks ignore outstanding calls and order reservations

Locations: [coverage check](../../trade_engine/risk_engine.py:523), [contract counting](../../trade_engine/risk_engine.py:169).

`NO_NAKED_OPTIONS` compares just the new request against all owned shares. It does not subtract existing short-call coverage, working option orders, or shares committed to equity sells. `_open_contracts()` counts filled calls but excludes working orders, so the separate contract cap misses reservations too. With 100 shares and one working call, the real risk evaluator **APPROVED** another call under the default one-contract cap. Combined coverage requires 200 shares.

Fix direction: calculate aggregate filled and reserved option exposure, including remaining quantities and equity-sale reservations. Apply it consistently at admission and pre-fill. This reproduction concerns the risk engine; it does not establish that a configured live adapter accepts option submission.

### 5. [P1] Equity sales can remove shares backing an open covered call

Location: [equity coverage rule](../../trade_engine/risk_engine.py:504).

The equity sell check subtracts pending equity sells but does not reserve shares for existing short calls. Reproduction with 100 shares and a filled short call **APPROVED** selling all 100 shares, leaving zero coverage. The Advisor has a separate CC conflict check, but direct execution uses this risk core and needs the same protection.

Fix direction: enforce post-sale underlying coverage against filled and reserved short-call obligations.

### 6. [P1] A temporary quote failure permanently strands an approved intent

Locations: [status change](../../trade_engine/execution_engine.py:516), [next-cycle selection](../../trade_engine/execution_engine.py:816).

The engine marks the intent `APPROVED` before fetching/validating the quote. A missing or rejected quote returns without an order or status rollback. Later cycles select only `PENDING` intents. Reproduction returned `QUOTE_UNAVAILABLE`, left `status='APPROVED'` and zero orders, and processed zero intents on the next cycle. A temporary provider outage therefore silently drops execution indefinitely.

Fix direction: preserve a retryable state until quote validation and durable order creation succeed, with explicit expiry/rejection behavior.

### 7. [P1] Stale holding prices silently become horizon outcomes

Locations: [learning price lookup](../../agents/learning/outcome_labeler.py:74), [recommendation outcome lookup](../../agents/outcome_evaluator.py:64).

Both lookups accept the newest cached price before the requested date without any age bound. The learning lookup calls its provider fallback only when no historical cache row exists at all. After a position is exited or data collection stops, a months-old price becomes the horizon price. Reproduction requested October 21 with a January 2 cached price of $100 and a stubbed provider price of $200: it returned $100 and never called the provider. These values feed persisted returns, alpha and learning labels.

Fix direction: accept only the target session's close or a bounded preceding-session substitute; otherwise fetch historical data or retain an unevaluable/retryable state. Preserve price dates and adjustment conventions in outcome provenance.

### 8. [P1] Multi-lot CSV holdings are double-counted in newsletter valuation

Location: [share override](../../send_newsletter_main.py:693).

The newsletter replaces **each CSV row** with the ticker's full `cost_lots` quantity, then sums the rows without aggregating the ticker. Reproduction used 40- and 60-share rows and 100 shares in the lot ledger: both rows became 100 shares, producing **$20,000 instead of $10,000** at a $100 quote. Portfolio/layer totals are inflated, while `holding_day`'s `(day,ticker)` replacement retains just one duplicate row, creating inconsistent aggregate and holding snapshots.

Fix direction: aggregate through the canonical position loader before any ledger override; reconcile quantities once per ticker.

### 9. [P2] Selling leaves stale snapshots or deletes valid history

Locations: [history purge](../../serve.py:2852), [today update](../../serve.py:2865).

A same-day full sale neither updates nor deletes today's row because the update requires positive remaining shares. Reproduction left a 100-share/$15,000 snapshot after all shares were sold. A backdated partial sale deletes **every subsequent holding row** before attempting today's update, so today's row is then absent and cannot be repaired by that update. Reproduction of a 20-share backdated sale left zero current rows instead of an 80-share position. Portfolio/layer aggregates are not brought into agreement either.

Fix direction: project current inventory consistently, handle zero holdings explicitly, and rebuild affected historical positions and aggregates instead of unconditionally deleting all later rows.

### 10. [P2] Undo and lot deletion leave authoritative holdings projections inconsistent

Locations: [undo](../../serve.py:2890), [lot deletion](../../serve.py:2726).

These operations mutate only SQLite lots/sales. They do not synchronize `holdings.csv`, daily snapshots or aggregates. Reproduction of a full sale followed by undo restored 100 lot shares but left the CSV empty; the CSV-driven snapshot/newsletter paths omit the restored position. Deleting the only lot left a 100-share CSV holding, so downstream code continues valuing a deleted position.

Fix direction: route add, sell, undo and delete through a shared portfolio mutation/projection service, including aggregate rebuilds and explicit recovery when a file projection fails.

### 11. [P2] FIFO sales do not update the surviving position's average cost

Location: [CSV sale update](../../serve.py:2838).

Only `Shares` changes. After FIFO removes a cheaper lot, `AvgCost` still includes that sold lot. Reproduction sold the 50 shares costing $100 from a 100-share position whose other 50 shares cost $200: remaining `AvgCost` stayed **$150 instead of $200**. CSV-based gain and covered-call cost-floor calculations use the wrong basis. Multiple matching CSV rows also each receive the full remaining ticker quantity.

Fix direction: compute both quantity and weighted cost from surviving lots and emit one canonical position row per ticker.

### 12. [P2] Lot-add accepts negative inventory

Location: [lot validation and insertion](../../serve.py:2620).

Validation checks only that fields are truthy. Negative shares, negative costs and malformed purchase dates reach storage; finite-number checks are also absent. Reproduction submitted `shares=-20` to a 100-share holding: the handler returned success, stored a negative lot, and reduced CSV inventory to 80 without recording a sale. Negative lots subsequently break FIFO assumptions.

Fix direction: validate finite, positive quantities, an explicit cost policy, and parsed purchase dates before any write.

### 13. [P2] New-position sizing caps omit working buy reservations

Location: [new-position rule](../../trade_engine/risk_engine.py:440).

The general position cap includes working buys, but `MAX_NEW_POSITION_WEIGHT` checks only the new intent's notional. While the symbol is not yet filled, multiple working buys each qualify independently. Reproduction approved another $500 buy with a $500 working buy and $10,000 NAV: **10% committed exposure despite the 5% new-position limit**.

Fix direction: include outstanding same-symbol buy reservations in initial-position exposure and define how partially filled initial entries retain the new-position limit.

### 14. [P2] Newsletter and dashboard use a federal holiday calendar as an exchange calendar

Locations: [newsletter calendar](../../send_newsletter_main.py:110), [dashboard calendar](../../generate_dashboard.py:39).

Both treat every US federal holiday as an exchange closure, disagreeing with the project's NYSE calendar. Reproduction: October 12, 2026 is classified closed by the newsletter and open by `trade_engine.market_calendar`. The newsletter writes zero daily changes, and dashboard chart filtering drops that session. The same mismatch occurs for Veterans Day.

Fix direction: use one exchange-session calendar for snapshot storage, chart filtering, learning horizons and execution.

### 15. [P2] Historical MTM repair includes future trades and current cash

Locations: [holdings reconstruction](../../agents/learning/book_mtm.py:59), [historical run](../../agents/learning/book_mtm.py:178), [cash loading](../../agents/learning/book_mtm.py:201).

`run_mark_to_market(date_str)` prices a historical date but reconstructs holdings from **all fills** and uses today's cash. Reproduction repaired September 21 with a purchase recorded October 20: the future position was included and the row was marked complete, yielding **$1,400 instead of $1,000**. Repairs after later trading silently rewrite historical returns with future information. Synthetic expiration exits also use wall-clock fill timestamps rather than the requested valuation date.

Fix direction: reconstruct both cash and holdings as of the requested session, include fees, and make generated exit timestamps/date semantics consistent with that session.

## Recommended repair order

1. Fix approved-thesis status handling, concurrent sells and undo inventory restoration.
2. Fix aggregate covered-call reservations, equity coverage preservation and quote-retry lifecycle.
3. Fix stale outcome pricing and duplicate newsletter aggregation before trusting learning/portfolio metrics.
4. Centralize portfolio mutation projections; repair historical data only after taking a consistent backup and determining which production rows were affected.
5. Correct remaining sizing, calendar and historical MTM semantics; add the reproduced scenarios to the relevant regression suites.

These are code-path reproductions, not a production-data audit. Whether historical production data was affected remains unverified.


## Tracked work

All findings are completed as TODOs **0745–0759** in the [bug-fix backlog](../../.todos/README.md). IDs map to finding order: finding 1 → 0745, through finding 15 → 0759.
