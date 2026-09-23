# Fix Timer Syntax, Service Exit Code, and Watchdog Immediacy

- **ID:** 0611
- **Status:** backlog
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0608

## Problem

Three operational correctness gaps remain after 0608. (a) The systemd timer uses `OnCalendar=America/New_York *-*-* 02:00:00`, which systemd rejects as invalid syntax — the timezone suffix must come last. (b) The maintenance CLI entry point (`run_news_maintenance`) always exits with code 0 even when `run_daily_sweep` returns `status='error'`; systemd therefore never marks the service as failed, defeating the point of failure propagation. (c) The watchdog staleness check only looks at the most recent *successful* run; if today's run fails but yesterday's succeeded, the component stays green for up to 26 hours before going YELLOW. A currently-failing run should surface immediately.

## Proposed approach

- **Timer:** Change `OnCalendar=America/New_York *-*-* 02:00:00` → `OnCalendar=*-*-* 02:00:00 America/New_York` (timezone suffix at end). Verify with `systemd-analyze calendar '*-*-* 02:00:00 America/New_York'`.
- **Exit code:** In the CLI entry point (`if __name__ == "__main__"` block or equivalent), call `sys.exit(1)` when the returned dict has `status='error'`. This causes systemd to report the service as failed.
- **Watchdog:** In `news_maintenance_check`, also query the most recent run regardless of status. If `status='error'` and it is more recent than the last `status='ok'` run, return YELLOW immediately (don't wait for the 26h staleness window).
- **Deployment:** After deploying to optiplex, verify with `systemd-analyze calendar`, `systemctl list-timers`, and confirm at least one successful `news_maintenance_log` row via `journalctl -u news-maintenance.service`.

## Touches

- `systemd/news-maintenance.timer` — OnCalendar timezone suffix correction
- `portfolio_ai.py` or the maintenance CLI entry point — `sys.exit(1)` on `status='error'`
- `operational_watchdog.py` — `news_maintenance_check` latest-failed-run immediate YELLOW
- `tests/test_news_intelligence.py` — test non-zero exit on error; test watchdog YELLOW on latest failed run even with prior successful run

## Done when

- [ ] `systemd-analyze calendar '*-*-* 02:00:00 America/New_York'` parses correctly on optiplex
- [ ] Optiplex systemd service reports `failed` (not `success`) when maintenance sweep fails
- [ ] Watchdog returns YELLOW immediately when the most recent run has `status='error'`, regardless of prior successful runs
- [ ] At least one successful `news_maintenance_log` row visible in `journalctl` after deployment
