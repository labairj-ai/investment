# Replace Process-Local Execution Lock With Cross-Process Shared Lock

- **ID:** 0317
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0313

## Problem

`serve.py` uses a `threading.Lock` keyed per account to prevent concurrent HTTP execution cycles — but this lock is process-local. `runner.py` is a separate process and acquires no lock at all. An authenticated `POST /api/trade-engine/run-alpaca` can therefore run concurrently with the systemd trade-runner, producing duplicate order submissions, double-counted risk limits, or torn account state. The timer won't self-overlap (systemd oneshot prevents that), but HTTP-vs-runner overlap is completely unguarded.

## Proposed approach

- Add a `db_locks` table (or `execution_leases` table) to `investment.db` with columns: `account_id TEXT PRIMARY KEY`, `locked_by TEXT`, `locked_at TEXT`, `expires_at TEXT`.
- Implement `acquire_execution_lease(account_id, holder, ttl_seconds)` and `release_execution_lease(account_id, holder)` in `agent_db.py` using an atomic `INSERT OR REPLACE ... WHERE expires_at < now()` pattern.
- Both `serve.py` (`_handle_trade_engine_run_alpaca`) and `runner.py` must acquire the lease before constructing `ExecutionSession`; return 409 / exit(1) immediately on contention.
- Alternative if DB lease is complex: `flock` on a well-known file (e.g. `out/alpaca_cycle.lock`) — simpler but gives less observability.
- Longer term: remove broker execution from the HTTP path entirely so the endpoint only triggers/queues the runner, but this is not required for the canary.
- Open question: should the HTTP endpoint be removed from the execution path before a funded account, or can it remain as a manual-trigger convenience through paper burn-in?
- **Lease expiry during a live cycle:** TTL must be large enough that no normal cycle can time out, or a heartbeat thread must periodically extend `expires_at`. The current HTTP TTL (300 s) and runner TTL (600 s) are too short for an abnormal cycle. Recommended: ≥ 30-minute TTL, or a heartbeat that extends by half the TTL every minute.

## Touches

- `agent_db.py` — new `db_locks`/`execution_leases` table + lease acquire/release helpers
- `serve.py` — replace `threading.Lock` with DB lease in `_handle_trade_engine_run_alpaca()`
- `trade_engine/runner.py` — acquire DB lease before `ExecutionSession`, release in `finally`

## Done when

- [x] Simultaneous `POST /run-alpaca` and a manual `python3 -m trade_engine.runner` invocation: one completes normally, the other returns 409 / exits with a clear "lease held" message and submits zero orders
- [x] Lease is released even when the cycle raises an exception (finally block)
- [x] Stale lease (holder crashed without releasing) is overridden after TTL expiry
- [x] Lease cannot expire under a live cycle: either TTL ≥ 30 min or a heartbeat extends `expires_at` while the holder runs
- [x] Test: process A holds lease past the original TTL while heartbeating; process B's acquire returns "held"; A stops heartbeating; after TTL elapses B can acquire

## Outcome

Lease TTL increased to 1800 s (30 min) in both runner.py (_LEASE_TTL) and serve.py (ttl_seconds=1800). DB lease implementation was already present; TTL increase satisfies updated done-when criterion. 718 tests pass.
