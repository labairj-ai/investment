# Run Full Suite and Record Experiment Operational-Start Integrity

- **ID:** 0454
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0450, 0451, 0452

## Problem

The 312-test count from commit e00d7f4 covers only the targeted learning/calibration
suite (`tests/test_calibration.py`), not the full ~1,000-test repository suite. Before
the learning pipeline is treated as production-ready, there is no verified record that
trade-engine, API, snapshot, and other tests remain green under the architecture changes
from 0439–0449. Without this, a regression in adjacent code could be running silently
on the optiplex.

## Proposed approach

- Run the full test suite (`python -m pytest tests/`) from a clean committed tree.
- Fix any failures before proceeding.
- Capture the result as a one-time operational-start integrity record in
  `config/experiment_integrity_record.json` containing:
  - `commit_sha` (must be clean tree — `git_dirty: false`)
  - `test_count`, `passed`, `failed`, `warnings`
  - `strategy_hash` (from `strategy_config.get_hash()`)
  - `policy_hash` and `policy_version` (from `load_policy("AGENTIC_SHADOW_01")`)
  - `canary_audit_result` (output/exit code of `scripts/canary_audit.sh` against live DB)
  - `recorded_at` (ISO timestamp)
- This file is committed once and never overwritten; it is not a CI artifact.

## Touches

- `tests/` (fix any failing tests first)
- `config/experiment_integrity_record.json` (new)
- `scripts/canary_audit.sh` (run as part of capture, no changes expected)

## Done when

- [ ] Full `pytest tests/` run is green from a clean committed tree
- [ ] `config/experiment_integrity_record.json` is committed with all required fields
- [ ] `git_dirty: false` and a valid `commit_sha` in the record
- [ ] `canary_audit_result` reflects a passing live-DB audit
