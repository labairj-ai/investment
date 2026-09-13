# Fix Reconciliation: Bidirectional Orders, Replay Overlap, LOCAL_MISSING Blocks

- **ID:** 0257
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0252

## Problem

Three related gaps remain in `reconciliation.py` and `initialize_trading_session()`:

1. **One-directional order check.** The reconciler loops over local open orders and
   checks whether each appears at the broker. It never iterates broker orders to ask
   "does the broker have an order that local state doesn't know about?" This is the key
   missing case after a crash-after-submit where no local `orders` row was written.

2. **LOCAL_MISSING is not blocking.** Broker-only positions are detected as
   `LOCAL_MISSING` discrepancies, but `LOCAL_MISSING` is not in `_BLOCKING_KINDS`, so
   unexplained broker-held positions or orders do not prevent new submissions.

3. **Late-fill cursor problem.** `initialize_trading_session()` advances the fill cursor
   to `max(filled_at)` of successfully imported fills. A broker that reports a fill late
   (e.g., fill executed at 10:04, reported at 10:06 after the cursor has advanced to
   10:05) will never be requested again. Additionally, when there are no imported fills
   and no prior cursor, the cursor is initialised to *now*, which can permanently skip
   fills that arrive shortly after with earlier `filled_at` timestamps.

## Proposed approach

1. **Bidirectional order reconciliation:**
   - After the existing local→broker pass, add a broker→local pass: for each order in
     `broker.get_open_orders()`, check whether a matching local `orders` row exists (by
     `client_order_id` first, then `broker_order_id`/`local_order_id`). If no local row
     exists, create a `LOCAL_MISSING` discrepancy.
   - On `LOCAL_MISSING` for an order: attempt to import the broker order into local state
     (create `orders` row in `WORKING` state) before blocking. The import should be
     attempted only when the broker order can be matched to a known `trade_intent` via
     `client_order_id`.

2. **Make LOCAL_MISSING blocking:**
   - Add `DiscrepancyKind.LOCAL_MISSING` to `_BLOCKING_KINDS` for both positions and
     orders when the discrepancy cannot be auto-resolved (no matching intent found).

3. **Replay-overlap cursor:**
   - Define a configurable `FILL_REPLAY_WINDOW` (e.g., 15 minutes).
   - Always query: `get_fills(since = last_cursor - FILL_REPLAY_WINDOW)`.
   - Rely on `apply_broker_fill()` idempotency (0252) to discard already-applied fills.
   - Never initialise the cursor to *now* on a fresh account; use a configured
     `account_inception_date` or leave it as `None` to fetch all fills on first run.

4. **Tests:**
   - Broker has order with known `client_order_id` but no local row → imported, not blocked.
   - Broker has order with unknown `client_order_id` → `LOCAL_MISSING` discrepancy, blocked.
   - Fill with `filled_at` earlier than `last_cursor - FILL_REPLAY_WINDOW` is not replayed.
   - Fill with `filled_at` within the replay window IS replayed and deduplicated.

## Touches

- `trade_engine/reconciliation.py`
- `trade_engine/execution_engine.py` — `initialize_trading_session()` cursor logic
- `trade_engine/policy.py` or config — `FILL_REPLAY_WINDOW` constant
- `tests/test_trade_engine.py`

## Done when

- [ ] Broker-only open order with known `client_order_id` is imported into local state
- [ ] Broker-only open order with unknown `client_order_id` produces `LOCAL_MISSING` that blocks submission
- [ ] `LOCAL_MISSING` is in `_BLOCKING_KINDS` (cannot be overridden without resolution)
- [ ] Fill cursor query uses `last_cursor - FILL_REPLAY_WINDOW` as start; late fills are replayed
- [ ] Fresh account does not initialise cursor to now; uses inception date or fetches all
- [ ] Replayed fills already in DB are silently skipped (deduplication via `apply_broker_fill()`)
- [ ] All existing tests pass
