# Fix Zero obs_id Bypasses Legacy Hysteresis Guard

- **ID:** 0395
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** none

## Problem

`_check_degradation()` legacy hysteresis path checks `elif last_max_obs_id is not None and int(last_max_obs_id) > 0`. If a snapshot was written with `last_snapshot_max_obs_id = 0` (possible when the first snapshot is created before any observations have integer IDs, or via a test/manual insert), the condition `int(0) > 0` is `False`, the elif is skipped, and execution falls through to the "no anchor" branch which fires unconditionally. The model could produce a new snapshot with no hysteresis enforcement.

## Proposed approach

- Change the guard to `int(last_max_obs_id) >= 0` so that a stored value of 0 still engages the legacy path (counting new observations since ID 0, which is effectively all observations). OR, change to `last_max_obs_id is not None` and let the downstream `WHERE id > 0` query return all rows if 0 is stored.
- More robust: default `last_snapshot_max_obs_id` to `NULL` (not `0`) on insert. Adjust the INSERT in `_check_degradation()` to write `NULL` rather than `0` when no prior observations existed.
- Add a test: insert a snapshot with `last_snapshot_max_obs_id=0` and verify hysteresis still fires (doesn't bypass).

## Touches

- `agents/learning/calibration.py` — `_check_degradation()` lines ~1338, ~1430
- `tests/test_calibration.py`

## Done when

- [ ] `last_snapshot_max_obs_id=0` engages legacy hysteresis path rather than bypassing it
- [ ] Test covers obs_id=0 anchor scenario
- [ ] Full test suite passes
