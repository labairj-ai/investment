# Fix Trade-Runner Timer: Timezone-Aware Schedule, No Catch-Up

- **ID:** 0318
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0313

## Problem

`systemd/trade-runner.timer` has two bugs. First, it carries four `OnCalendar` entries (13:45, 14:45, 17:00, 19:45 UTC) to work around DST — this fires an extra cycle every day, and 13:45 UTC lands at 8:45 AM ET in winter (EST), which is before market open. Second, `Persistent=true` causes any missed cycles (e.g. after a reboot) to fire immediately at startup regardless of time of day, which is unsafe for an autonomous trading timer.

## Proposed approach

- Replace all four UTC `OnCalendar` lines with three timezone-aware entries using systemd's `TIMEZONE=` directive in the `[Timer]` section (supported since systemd 242):
  ```
  [Timer]
  TIMEZONE=America/New_York
  OnCalendar=Mon..Fri *-*-* 09:45:00
  OnCalendar=Mon..Fri *-*-* 12:00:00
  OnCalendar=Mon..Fri *-*-* 15:45:00
  ```
- Remove `Persistent=true`.
- Before deploying, verify optiplex systemd version supports `TIMEZONE=`: `systemctl --version`. If < 242, fall back to a single UTC window covering EDT/EST overlap (e.g. 14:45, 17:00, 20:45 UTC — three entries, no duplicates).

## Touches

- `systemd/trade-runner.timer`
- Deploy: copy updated file to `/etc/systemd/system/trade-runner.timer` on optiplex, then `sudo systemctl daemon-reload && sudo systemctl restart trade-runner.timer`

## Done when

- [ ] Timer fires exactly three times on a weekday, all within US market hours for both EST and EDT
- [ ] `systemctl list-timers trade-runner.timer` shows next trigger inside 09:30–16:00 ET window
- [ ] A reboot during off-hours does not trigger an immediate trade cycle
