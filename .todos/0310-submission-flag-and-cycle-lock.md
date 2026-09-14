# Add Submission Feature Flag and Single-Flight Execution Lock

- **ID:** 0310
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0308, 0309

## Problem

Two independent safety gaps in the Alpaca execution path:

1. `_handle_trade_engine_run_alpaca()` hardcodes `submission_enabled=True` unconditionally — there is no operational kill switch short of editing code or disabling the service. A bad deployment, stale policy, or runaway scheduler should be stoppable with a single env-var change.

2. `ThreadingHTTPServer` allows two concurrent `POST /api/trade-engine/run-alpaca` requests to run overlapping `ExecutionSession` cycles for `AGENTIC_ALPACA_01`. Both can read the same `PENDING` intent and both can reach `broker.submit_order()` before the DB uniqueness constraint fires, making the broker the de-facto concurrency lock — which it should not be.

## Proposed approach

**Feature flag:**
- Only set `submission_enabled=True` when `ALPACA_PAPER_SUBMISSION_ENABLED == "1"` (env var, default absent = off).
- Also check `policy.trading_enabled()` before enabling submission; return a clear error if the policy circuit breaker is tripped.
- Add `ALPACA_PAPER_SUBMISSION_ENABLED=1` to optiplex override only after 0308 and 0309 are done.

**Single-flight lock:**
- Add a module-level `threading.Lock` keyed to `"AGENTIC_ALPACA_01"` in `serve.py`.
- In `_handle_trade_engine_run_alpaca()`, acquire the lock non-blocking (`Lock.acquire(blocking=False)`); return 409 immediately if another cycle is already running.
- Note: a `threading.Lock` is sufficient only while execution lives in `serve.py`. Once execution moves to a separate process (see 0312), replace with a DB `execution_leases` table with an atomic claim and TTL-based expiry.

**Tighten initial paper policy limits** in `config/trading_policy_agentic_alpaca_01.json`:
- `max_orders_per_day: 1`
- `max_new_position_pct: 1`
- `max_single_position_pct: 2`
- `max_daily_notional_pct: 2`

## Touches

- `serve.py` — feature flag check, module-level lock, 409 on contention
- `config/trading_policy_agentic_alpaca_01.json` — tighter initial limits
- `/etc/systemd/system/investment.service.d/override.conf` on optiplex — `ALPACA_PAPER_SUBMISSION_ENABLED`

## Done when

- [ ] With `ALPACA_PAPER_SUBMISSION_ENABLED` absent or `"0"`, `run-alpaca` returns an error and no order is submitted
- [ ] With flag `"1"` and policy `trading_enabled=true`, submission proceeds normally
- [ ] Two simultaneous `POST /run-alpaca` requests: one returns 409, one completes; no duplicate broker submissions
- [ ] Paper policy limits updated to the conservative burn-in values listed above
