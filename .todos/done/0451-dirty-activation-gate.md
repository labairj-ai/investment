# Block PAPER_ACTIVE Promotion on Dirty Worktree

- **ID:** 0451
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0448

## Problem

`promote()` captures `git_dirty` in the activation snapshot but does not enforce
cleanliness for PAPER_ACTIVE transitions. When `git_dirty=True`, `activation_commit_sha`
names a commit that does not fully describe the running code — the actual tree diverges
from it. The provenance system being built is only meaningful if the SHA is trustworthy,
and a dirty-tree activation silently breaks that guarantee.

## Proposed approach

- Add a dirty-tree check inside the existing PAPER_ACTIVE provenance gate (alongside
  `_PAPER_ACTIVE_REQUIRED`): if `snapshot.get("git_dirty") is True` and no
  `override_reason` is supplied, block the promotion with
  `{"promoted": False, "error": "dirty_worktree", ...}`.
- If `git_dirty` is absent from the snapshot (git unavailable), treat it as a
  `snapshot_error` only — do not block, since you can't enforce cleanliness you
  can't measure.
- OBSERVE transitions: no enforcement, same as today.
- Add a test: promote to PAPER_ACTIVE with `git_dirty=True` in snapshot (mock git to
  return dirty output) without `override_reason` → blocked; with `override_reason` →
  allowed.

## Touches

- `agents/learning/calibration.py` (`promote()`, PAPER_ACTIVE gate block)
- `tests/test_calibration.py`

## Done when

- [ ] PAPER_ACTIVE promotion is blocked when `git_dirty=True` and `override_reason` is absent
- [ ] PAPER_ACTIVE promotion proceeds when `git_dirty=True` and `override_reason` is supplied
- [ ] Absent `git_dirty` (git unavailable) does not block the promotion
- [ ] Test covers all three cases
