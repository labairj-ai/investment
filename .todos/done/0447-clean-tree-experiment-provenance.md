# Record Git Cleanliness in Baseline and Activation Snapshots

- **ID:** 0447
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0446

## Problem

Both `experiment_baseline.json` and the model activation snapshot written by
`promote()` record `git_commit_sha`, but not whether the worktree was clean at the
time. If the tree was dirty, the SHA does not fully describe the code that was
running — the snapshot looks authoritative but may not be. The committed baseline in
`a8ba5ea` already demonstrates this: the SHA it records (`752b678`) predates the
commit that added the changes used to generate the file.

## Proposed approach

- Add a `_git_dirty()` helper (in `freeze_baseline.py` and reusable from
  `calibration.py`) that runs `git status --porcelain` and returns `True` if any
  tracked or staged files differ from HEAD.
- Record `git_dirty: true/false` alongside `git_commit_sha` in both the baseline
  JSON and the `promotion_metrics_snapshot`.
- In `freeze_baseline.py`, if the tree is dirty at freeze time, abort with an error
  message unless `--force` is passed. The intended workflow:
  1. Commit all scoring/config code changes.
  2. Verify clean tree.
  3. Run `freeze_baseline.py` (no `--force` needed).
  4. Commit the resulting JSON separately.
  The JSON then references the preceding source-code commit exactly.
- After implementing, regenerate `config/experiment_baseline.json` from a clean
  committed state and recommit so the frozen snapshot reflects a clean tree.
- `promote()` in `calibration.py` should also capture `git_dirty` in the activation
  snapshot (best-effort; promotion is not blocked if git is unavailable).

## Touches

- `scripts/freeze_baseline.py`
- `agents/learning/calibration.py` (promote snapshot)
- `config/experiment_baseline.json` (regenerated from clean tree)

## Done when

- [ ] `freeze_baseline.py` records `git_dirty` in the output JSON
- [ ] `freeze_baseline.py` aborts when `git_dirty=true` unless `--force` is passed
- [ ] `promote()` records `git_dirty` in `promotion_metrics_snapshot` (best-effort)
- [ ] `config/experiment_baseline.json` is regenerated from a clean worktree and recommitted, with `git_dirty: false`
