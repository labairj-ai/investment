# Make apply_broker_fill Idempotent on Duplicate Fill ID

- **ID:** 0252
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** none

## Problem

`apply_broker_fill()` uses `INSERT OR IGNORE INTO fills` to deduplicate fill rows, but
then unconditionally proceeds to update `orders.fill_qty`, `position_snapshots.qty`, and
`trading_accounts.current_cash` regardless of whether the INSERT actually wrote a new
row. A broker reconnect or event-replay that re-delivers fill F123 will correctly leave
the fills table with one row, but will add shares and subtract cash a second time —
corrupting account state in a way that is invisible to the fill table.

This is the defect the hostile-broker tests (0249) were intended to catch but don't,
because the chaos test calls `attempt_fill()` once rather than feeding a duplicated event
through `apply_broker_fill()`.

## Proposed approach

1. Before (or atomically with) the INSERT, determine whether the fill was already applied.
   Two acceptable approaches:
   - Query for `fill_id` existence inside the same transaction before the INSERT; skip all
     mutations if the row is found.
   - Use `conn.execute("INSERT OR IGNORE …").rowcount` — if rowcount == 0, the row
     already existed; return immediately without any further mutation.
2. Wrap the entire function in an explicit `BEGIN` / `COMMIT` / `ROLLBACK` block so any
   partial failure leaves the DB unchanged.
3. Define a return value (e.g., an enum `FillResult.APPLIED` / `FillResult.ALREADY_APPLIED`)
   so callers can distinguish new vs. replayed fills.
4. Add a test: construct a `BrokerFill`, call `apply_broker_fill()` twice with the
   identical object, then assert that `fills` count == 1, `orders.fill_qty` did not
   double, `position_snapshots.qty` did not double, and `current_cash` equals the
   expected value for exactly one fill — not two.

## Touches

- `trade_engine/execution_engine.py` — `apply_broker_fill()`
- `tests/test_trade_engine.py` — new `TestApplyBrokerFillIdempotency` class

## Done when

- [ ] Calling `apply_broker_fill()` twice with the same `broker_fill_id` leaves `fills` count == 1
- [ ] `orders.fill_qty` is not incremented on the second call
- [ ] `position_snapshots.qty` is not incremented on the second call
- [ ] `current_cash` is not decremented on the second call
- [ ] The function is wrapped in an explicit transaction; any exception triggers a rollback
- [ ] Return value distinguishes `APPLIED` from `ALREADY_APPLIED`
- [ ] All existing tests pass
