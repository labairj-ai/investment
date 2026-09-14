# Fix Trade-Runner Timer: Timezone-Aware Schedule, No Catch-Up

- **ID:** 0318
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0313

## Problem

`systemd/trade-runner.timer` has two bugs. First, it carries four `OnCalendar` entries (13:45, 14:45, 17:00, 19:45 UTC) to work around DST — this fires an extra cycle every day, and 13:45 UTC lands at 8:45 AM ET in winter (EST), which is before market open. Second, `Persistent=true` causes any missed cycles (e.g. after a reboot) to fire immediately at startup regardless of time of day, which is unsafe for an autonomous trading timer.

## Proposed approach

- `TIMEZONE=` is **not a valid `[Timer]` directive** — it silently has no effect. The timezone must go inside each `OnCalendar=` expression:
  ```
  [Timer]
  OnCalendar=Mon..Fri *-*-* 09:45:00 America/New_York
  OnCalendar=Mon..Fri *-*-* 12:00:00 America/New_York
  OnCalendar=Mon..Fri *-*-* 15:45:00 America/New_York
  ```
- Remove `Persistent=true`.
- Validate on optiplex before deploying:
  - `systemd-analyze verify /etc/systemd/system/trade-runner.timer` — must produce no errors
  - `systemd-analyze calendar "Mon..Fri *-*-* 09:45:00 America/New_York"` — confirm next fire inside ET window
  - After reload: `systemctl list-timers trade-runner.timer`

## Touches

- `systemd/trade-runner.timer`
- Deploy: copy updated file to `/etc/systemd/system/trade-runner.timer` on optiplex, then `sudo systemctl daemon-reload && sudo systemctl restart trade-runner.timer`

## Done when

- [x] Timer file uses inline timezone in `OnCalendar=` expressions, no `TIMEZONE=` directive
- [x] `systemd-analyze verify` produces no errors or warnings for the timer unit
- [x] Timer fires exactly three times on a weekday, all within US market hours for both EST and EDT
- [x] `systemctl list-timers trade-runner.timer` shows next trigger inside 09:30–16:00 ET window
- [x] A reboot during off-hours does not trigger an immediate trade cycle

## Outcome

Fixed systemd/trade-runner.timer: TIMEZONE= directive removed; timezone embedded inline in each OnCalendar= expression (e.g. "Mon..Fri *-*-* 09:45:00 America/New_York"). Validate on optiplex: systemd-analyze verify trade-runner.timer.
