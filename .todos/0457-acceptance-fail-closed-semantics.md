# Require Clean Git State and Healthy Integrity for Acceptance PASS

- **ID:** 0457
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0456

## Problem

`first_sweep_acceptance.py` has two fail-open holes that contradict the
fail-closed design used everywhere else. First: acceptance only fails when
`integrity_overall == "BLOCK"` — if the audit crashes or returns an unknown
status the result is `"error"`, which is not `"BLOCK"`, so the script can write
a permanent PASS artifact despite an unverified integrity state. Second: the
artifact records `source_commit_sha` and `git_dirty` but neither is validated
before writing — a permanently-recorded acceptance could carry
`source_commit_sha: null` or `git_dirty: true`, silently weakening the
provenance chain the rest of the architecture was built to guarantee.

## Proposed approach

- **Integrity:** require `integrity_overall == "ok"` for a clean PASS. Treat
  `"BLOCK"`, `"error"`, any unrecognised status, and — for a one-time freeze
  record — `"WARN"` as failures. If WARN should ever be waivable, require an
  explicit `--waive-integrity-warn` flag that is recorded in the artifact.
- **Git state:** before writing any acceptance artifact, assert that `_git_sha()`
  returns a non-null value and `_git_dirty()` returns `False`. If either
  condition fails, abort with a descriptive error:
  - `source_commit_sha is None` → "git unavailable; cannot write authoritative acceptance record"
  - `git_dirty is True` → "worktree is dirty; commit all changes before acceptance"
- **Tests:** add to `tests/test_first_sweep_acceptance.py` (new file or inline):
  - integrity `"error"` → acceptance FAIL
  - integrity `"WARN"` → acceptance FAIL (without waiver)
  - integrity unknown string → acceptance FAIL
  - `git_dirty=True` → artifact write aborted
  - `source_commit_sha=None` → artifact write aborted

## Touches

- `scripts/first_sweep_acceptance.py`
- `tests/test_first_sweep_acceptance.py` (new)

## Done when

- [ ] Only `integrity_overall == "ok"` (or explicitly waived WARN) allows PASS
- [ ] `"error"` and unrecognised integrity statuses cause acceptance to FAIL
- [ ] `source_commit_sha` is required non-null before writing the artifact
- [ ] `git_dirty == False` is required before writing the artifact
- [ ] Tests cover all four new failure paths
