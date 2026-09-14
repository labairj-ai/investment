# Split Broker Execution into Dedicated systemd Trade-Runner Service

- **ID:** 0313
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0308, 0309, 0310, 0312

## Problem

`serve.py` is simultaneously the network-facing dashboard server and the process that holds Alpaca broker credentials and can submit orders. Any bug, misconfiguration, or compromise in the dashboard layer directly exposes the execution path and the broker secret. There is also no autonomous execution cadence — cycles only run when an HTTP endpoint is called. For credible paper (and eventual funded) trading, execution must be independent of the web server.

## Proposed approach

- New script `trade_engine/runner.py` (or `trade_runner.py`): reads `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `ALPACA_PAPER_ACCOUNT_ID`, `ALPACA_PAPER_SUBMISSION_ENABLED` from env; opens `investment.db` directly; constructs `AlpacaAdapter` + `ExecutionSession`; runs one cycle and exits. Logs to journald via `logging`.
- New systemd units on optiplex:
  - `trade-runner.service` — one-shot service running `trade_engine/runner.py`
  - `trade-runner.timer` — fires every 5 minutes; the runner checks `market_calendar` itself and exits early outside market hours
- `serve.py` changes:
  - Remove `ALPACA_API_KEY` / `ALPACA_API_SECRET` from `investment.service` override entirely
  - `/api/trade-engine/run-alpaca` becomes either: (a) an authenticated admin trigger that writes a signal the runner polls, or (b) a stub that returns 501 once the runner is primary
- Replace the `threading.Lock` from 0310 with a DB `execution_leases` table (atomic `INSERT OR FAIL`, TTL-based expiry via `acquired_at + expires_seconds`) so the timer-driven runner and any admin HTTP trigger cannot overlap across processes
- Open question: does `/run-alpaca` stay as an authenticated out-of-band trigger (useful for manual testing) or get removed entirely once the timer is running?

## Touches

- `trade_engine/runner.py` (new)
- `serve.py` — strip broker creds from env, repurpose or stub `/run-alpaca`
- `/etc/systemd/system/trade-runner.service` + `trade-runner.timer` on optiplex (new)
- `/etc/systemd/system/investment.service.d/override.conf` — remove `ALPACA_API_KEY` / `ALPACA_API_SECRET`
- `agent_db.py` or `trade_engine/execution_engine.py` — `execution_leases` table schema

## Done when

- [ ] `trade-runner.timer` fires every 5 min; runner exits immediately outside NYSE market hours
- [ ] `serve.py` process has no access to `ALPACA_API_KEY` or `ALPACA_API_SECRET`
- [ ] Concurrent timer fire + admin trigger attempt: one acquires DB lease, other exits without submitting
- [ ] Runner logs cycle summary (intents processed, orders submitted, halted/ok) to journald
- [ ] `investment.service` restarts cleanly without broker credentials in its env
