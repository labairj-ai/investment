# Fix Maintenance Sweep Truthfulness and Timer Correctness

- **ID:** 0608
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0605

## Problem

Two operational correctness gaps. (a) `update_event_state_sweep()` catches all exceptions internally and returns `counts=0` without raising, so `run_daily_sweep()` records `status='ok'` even when the sweep silently failed. The watchdog sees a recent `ok` row and stays green — a false positive that defeats the purpose of the audit log. (b) The systemd timer uses `OnCalendar=*-*-* 07:00:00` with a comment claiming "02:00 ET (07:00 UTC)", but Eastern Time is currently UTC-4 (EDT), making 07:00 UTC = 03:00 ET. The timer fires one hour late during daylight saving.

## Proposed approach

- **Sweep truthfulness:** Remove the bare `except` in `update_event_state_sweep()` so exceptions propagate to `run_daily_sweep()`. Catch them there, set `status='error'`, persist the error message, and let the watchdog distinguish `status='ok'` (valid heartbeat) from `status='error'` (sweep attempted but failed). Watchdog `news_maintenance_check` must filter `WHERE status='ok'` when computing the last-run timestamp.
- **Timer timezone:** Replace `OnCalendar=*-*-* 07:00:00` with an `OnCalendar` expression that uses `America/New_York` as the timezone so DST is handled automatically. Systemd supports `TZ=` or `OnCalendar=` with a timezone suffix on recent versions; fall back to documenting the UTC offset per season if not available on this host.
- **Deployment verification:** After deploying to optiplex, confirm with `systemctl is-enabled news-maintenance.timer`, `systemctl list-timers`, and `journalctl -u news-maintenance.service`, and check for a successful `news_maintenance_log` row.

## Touches

- `agents/news/intelligence.py` — `update_event_state_sweep()` exception handling
- `agents/news/maintenance.py` — `run_daily_sweep()` status propagation on sweep failure
- `operational_watchdog.py` — `news_maintenance_check` must only count `status='ok'` rows
- `systemd/news-maintenance.timer` — timezone-correct `OnCalendar`
- `tests/test_news_intelligence.py` — test that a sweep exception → `status='error'` in log; watchdog reports YELLOW on all-error log

## Done when

- [ ] If `update_event_state_sweep()` raises, `run_daily_sweep()` records `status='error'` (not `'ok'`) in `news_maintenance_log`
- [ ] Watchdog `news_maintenance` check queries `WHERE status='ok'`; an all-error log produces a YELLOW result
- [ ] `systemd/news-maintenance.timer` fires at 02:00 ET year-round (DST-correct)
- [ ] Optiplex shows timer enabled and at least one successful `news_maintenance_log` row via `journalctl`
