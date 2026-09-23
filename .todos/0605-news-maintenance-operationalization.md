# Operationalize Daily News Event-State Maintenance

- **ID:** 0605
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0602

## Problem

`update_event_state_sweep()` was moved earlier in `generate_news_summaries()` in 0602, but it still runs after the `if not ollama_client.available(): return` guard and after `news_fetcher.fetch()`. If the MLX server is down or the news fetch raises, the sweep never runs — defeating the independence goal. FADING/RESOLVED state maintenance must not depend on MLX health, news-provider health, dashboard usage, or news volume. Additionally, there is no audit trail for sweep runs, so the watchdog has no signal to check.

## Proposed approach

- Create `agents/news/maintenance.py` with a single public function `run_daily_sweep(day=None)` that opens its own DB connection, calls `update_event_state_sweep()`, records a row in a new `news_maintenance_log` table (`run_at`, `day`, `active_count`, `fading_count`, `resolved_count`, `status`, `error`), and closes cleanly. No imports from `portfolio_ai`; no dependency on ollama or news_fetcher.
- Add a `run_news_maintenance` entry point in `portfolio_ai.py` (or a thin CLI script) callable from systemd.
- Add a systemd timer on optiplex: daily at a fixed time (e.g. 02:00 ET), independent of the investment dashboard timer.
- Keep the existing call inside `generate_news_summaries()` — it is idempotent and catches the common path cheaply.
- Wire into watchdog health check: query `MAX(run_at) FROM news_maintenance_log`; alert if > 26 hours ago.

## Touches

- `agents/news/maintenance.py` (new)
- `agents/news/intelligence.py` (`update_event_state_sweep` returns counts for audit row)
- `portfolio_ai.py` (`_init_ai_tables` for `news_maintenance_log`; standalone entry point)
- `optiplex` systemd timer unit file
- watchdog health-check script
- `tests/test_news_intelligence.py` (sweep runs and records audit row regardless of MLX state)

## Done when

- [ ] `run_daily_sweep()` in `agents/news/maintenance.py` runs and commits successfully with no imports from `ollama_client`, `news_fetcher`, or `portfolio_ai`
- [ ] Each run inserts one row into `news_maintenance_log` with `run_at`, `day`, and ACTIVE/FADING/RESOLVED counts
- [ ] Systemd timer on optiplex triggers `run_daily_sweep` once daily, independent of the investment dashboard
- [ ] Watchdog alerts if `MAX(run_at)` in `news_maintenance_log` is more than 26 hours old
- [ ] Test: simulate MLX-unavailable (mock `ollama_client.available()` → False), call `generate_news_summaries()`, confirm sweep still ran (audit row present)
