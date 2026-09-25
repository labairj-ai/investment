# Fix Remaining Concrete Timezone Violations

- **ID:** 0682
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0669

## Problem

Several concrete violations remain post-batch:

1. **`serve.py` persistence bug**: `ai_analysis_at` and `ai_layer_rank_at` are still written using `datetime.datetime.now().strftime(...)` — host-local time. There is also a UTC write path for `ai_analysis_at`, meaning the same column can receive either UTC or host-local time depending on which code path ran. This is an active data integrity issue.

2. **Option/DTE/date-window calculations**: Several business/calendar calculations in `serve.py` use `datetime.now()` for option DTE, expiration inference, near-term expiry windows, and scan elapsed time. These should use `now_utc().astimezone(TZ_EASTERN)` or a `today_eastern()` helper so they don't depend on the server's local timezone.

3. **Dashboard age calculations**: Age/freshness calculations in `generate_dashboard.py` use naive `datetime.now()`. Should use UTC-aware datetimes.

4. **Challenger Trainer systemd timer**: `systemd/challenger-trainer.timer` uses `TIMEZONE=America/New_York` + `OnCalendar=Mon..Fri *-*-* 19:00:00`. That form is invalid — `TIMEZONE=` is not how systemd timer timezones work. It should be `OnCalendar=Mon..Fri *-*-* 19:00:00 America/New_York` (inline timezone suffix), matching the correct pattern already used by the trade runner, outcome labeler, book MTM, news maintenance, and macro preparation timers.

## Proposed approach

- Replace both `ai_analysis_at`/`ai_layer_rank_at` persistence calls in `serve.py` with `now_utc_iso()` from `time_utils`.
- Unify the `ai_analysis_at` write paths so both use the same UTC helper (no mixed-format risk).
- Add a `today_eastern()` convenience to `time_utils.py` → `now_utc().astimezone(TZ_EASTERN).date()`. Replace option/DTE/expiry date calculations with it.
- Replace naive `datetime.now()` in dashboard age calculations with `now_utc()`.
- Fix `systemd/challenger-trainer.timer`: remove `TIMEZONE=` line, add `America/New_York` suffix to `OnCalendar`. Deploy updated timer on optiplex (`systemctl daemon-reload && systemctl restart challenger-trainer.timer`).

## Touches

- `serve.py` — `ai_analysis_at`, `ai_layer_rank_at`, option/DTE calculations
- `generate_dashboard.py` — age/freshness calculations
- `time_utils.py` — add `today_eastern()` helper
- `systemd/challenger-trainer.timer` — fix `OnCalendar` timezone syntax
- `tests/` — assert `ai_analysis_at` write produces UTC value; test `today_eastern()`

## Done when

- [x] `ai_analysis_at` and `ai_layer_rank_at` both written as UTC in all code paths
- [x] Option/DTE/expiry calculations use `today_eastern()` (not host-local `date.today()`)
- [x] Dashboard age calculations use UTC-aware datetimes
- [x] `challenger-trainer.timer` uses inline `America/New_York` suffix on `OnCalendar`
- [x] Timer deployed and reloaded on optiplex
- [x] CI guard from 0681 no longer flags any of these call sites
- [x] Tests pass; production canary clean
