# Require Known-Clean Git State Before Writing Artifact

- **ID:** 0461
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** none

## Problem

`_git_dirty()` returns `True`, `False`, or `None`, where `None` means the git status subprocess failed or could not be determined. The artifact-write gate currently checks `if dirty is True: exit 3`, so a run where git status is unknowable (`None`) is allowed through and writes an authoritative artifact with `"git_dirty": null`. The 0457 acceptance criterion requires `git_dirty == False` — a known-clean state — not merely "not known to be dirty."

## Proposed approach

- Change the gate from `if dirty is True` to `if dirty is not False`, so both `True` and `None` block artifact creation with exit 3.
- Add a test that mocks `_git_dirty()` to return `None` and asserts the CLI exits with code 3 and writes no artifact.
- Confirm the existing `dirty=True` test still passes and the `dirty=False` path still writes normally.

## Touches

- `Desktop/investment/` — acceptance CLI where the `_git_dirty()` gate lives (exact filename unknown)
- `Desktop/investment/tests/` — new test for `_git_dirty() → None` being blocked

## Done when

- [ ] `_git_dirty()` returning `None` causes exit 3 and no artifact is written
- [ ] Test explicitly covers the `None` case
- [ ] Artifact `"git_dirty"` field is never `null` in a written acceptance artifact
