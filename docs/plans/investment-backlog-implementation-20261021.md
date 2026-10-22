# Investment backlog implementation — 0745–0759

All 15 backlog items are implemented locally and archived in `.todos/done/`.

## What changed

- Thesis readers accept canonical ACTIVE and legacy casing; new/migrated statuses are canonical. Ambiguous CC policies fail closed, and assignment-policy changes participate in invalidation hashes.
- `portfolio_mutations.py` serializes new holdings, added lots, sales, undo and deletion across processes. FIFO inventory is read under the write reservation. Only undone shares are restored. CSV output is atomic, canonical per ticker and backed by durable idempotency/projection receipts.
- Dated position snapshots are reconstructed from the surviving acquisition/sale ledger. Quotes survive full exits so undo can restore snapshots. Holding, layer and portfolio values/weights reconcile; surviving FIFO basis is recomputed.
- Invalid quantities/costs/dates are rejected before inventory writes. Zero-basis acquisitions are supported; negative/nonfinite costs and quantities are rejected.
- Risk checks reserve filled and working calls, pending submissions/cancels and equity-sale coverage. New-position limits include working buys and partial initial fills. Quote misses remain retryable; durable PENDING_SUBMIT ownership remains unchanged.
- Newsletter rows are aggregated before ledger overrides. Newsletter and dashboard use the existing exchange calendar.
- Outcome prices require the appropriate exchange session. New ticker, excursion and benchmark math uses unadjusted closes; the benchmark has a separate versioned-basis cache. Missing placeholders can complete, valid labels remain unchanged, and new labels carry price-basis/session provenance. Recommendation dates use Eastern business dates.
- Historical virtual-book NAV reconstructs holdings and cash through the requested Eastern session, including fees. Future fills are excluded; repairs leave current cash alone. Synthetic exits use effective session dates. Following complete returns are recalculated after a repaired mark.

## Validation

Full suite: **2,633 passed, 16 skipped, zero failures**. Final focused checks after the last refinements: **172 passed**. New backlog regressions cover inventory races/conservation, out-of-order undo, snapshots and basis, projection recovery/idempotency, HTTP mutation handlers, validation/aliases, thesis approval/policies, committed option/share exposure, quote retry, session pricing, unadjusted benchmark isolation, placeholders, duplicate newsletter lots and historical MTM.

The four previously date-sensitive fixtures now use explicit corpus clocks. Lifecycle price fixtures seed exchange sessions instead of depending on stale-price substitution. No release waiver was added. Exact failure-inventory and trusted-prior covered-call contract checks pass.

[Validation receipt](../evidence/investment-backlog-implementation-20261021/validation.json), [full-suite summary](../evidence/investment-backlog-implementation-20261021/full-suite-summary.txt), [focused results](../evidence/investment-backlog-implementation-20261021/focused-tests.txt), [covered-call authorization](../evidence/investment-backlog-implementation-20261021/covered-call-contract.txt).

## Recovery and production data

A mutation response includes `request_id`. Send that ID as `Idempotency-Key` or `request_id` when retrying the same request. A committed mutation with an unfinished CSV projection returns HTTP 503 with `committed=true` and its request ID. The next mutation/retry first flushes durable pending projections. Reusing an ID for a different request is rejected.

Historical production rows have not been repaired and no deployment was performed. The diagnostic is read-only and does not run migrations:

```sh
venv/bin/python scripts/audit_portfolio_inventory.py --project /path/to/investment
```

It reports invalid lots, duplicate/mismatched CSV positions, snapshot totals, orphan approved intents, ambiguous theses, pending projections, outcome-cache review candidates and historical NAV/cash/quantity discrepancies. Outcome cache gaps are candidates for review, not proof of corruption. Run against the authoritative database after copying/deploying the reviewed diagnostic; this local Mac database is not authoritative.

Before historical repair: take a consistent SQLite/CSV backup, freeze affected IDs and old values, rebuild on a copy using the corrected paths, reconcile quantities/cash/basis/snapshot totals and returns, and retain a correction receipt. Do not overwrite valid legacy learning labels: register corrected evidence under an explicit new cohort/horizon contract and preserve old provenance. Old mixed-basis benchmark rows are retained; new calculations use the dedicated unadjusted cache.

Historical MTM repair is valuation-only: it does not backdate synthetic trades into current cash. Missing historical execution evidence needs an explicit reconciled fill, not an inferred trade.

## TODO mapping

See the [completed backlog index](../../.todos/README.md). Each item records its affected implementation and validation evidence. The original [deep review](investment-deep-review-20261021.md) remains historical evidence; its bug-reproduction script is not an acceptance suite for fixed behavior.
