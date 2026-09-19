# Amend Experiment Baseline Provenance Without Overwriting History

- **ID:** 0450
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0447

## Problem

`config/experiment_baseline.json` was generated before the 0447 format was in place: it
lacks a `git_dirty` field and its `git_commit_sha` (752b678) predates the baseline-format
fixes. The 0447 todo explicitly required regenerating the baseline from a clean worktree
after the format was finalized, but that step was skipped. Because the baseline is
treated as immutable provenance history, the fix must NOT be a silent overwrite — doing
so would erase the original event record.

## Proposed approach

- **Preferred (append-only amendment):** create
  `config/experiment_baseline_amendment_001.json` that records:
  - `original_frozen_at` and `original_commit_sha` (copied from the existing baseline)
  - `amendment_commit_sha` — the new clean-tree SHA
  - `git_dirty: false`
  - `amendment_reason` — "provenance format upgrade; no experiment conditions changed"
  - `strategy_formula_changed: false`, `policy_changed: false`, `capital_contract_changed: false`
  This preserves the original event and establishes a verified clean-tree checkpoint.
- **Alternative (explicit reset):** if the experiment has not formally started, archive
  the existing file as `config/experiment_baseline_legacy.json`, declare a new experiment
  start, and run `freeze_baseline.py` from a clean committed tree. This should be a
  conscious decision, not an accidental rerun.
- Optionally add an `--amend` mode to `freeze_baseline.py` that writes the amendment
  file rather than overwriting the primary baseline.
- The choice between the two approaches should be made deliberately before implementing.

## Touches

- `config/experiment_baseline.json` (read-only reference; not overwritten in preferred approach)
- `config/experiment_baseline_amendment_001.json` (new, preferred approach)
- `scripts/freeze_baseline.py` (possibly new `--amend` flag)

## Done when

- [ ] A deliberate choice is made between amendment and explicit reset (documented in the file)
- [ ] The existing `experiment_baseline.json` is either preserved intact or archived with a clear reason
- [ ] A clean-tree provenance record exists with `git_dirty: false` and a matching commit SHA
- [ ] The amendment/new baseline is committed and pushed
