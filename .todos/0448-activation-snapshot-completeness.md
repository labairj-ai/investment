# Require Complete Provenance for PAPER_ACTIVE Promotion

- **ID:** 0448
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0443, 0447

## Problem

`promote()` wraps every provenance capture (git SHA, strategy hash, policy hash,
evidence contract) in bare `try/except: pass`, so a PAPER_ACTIVE promotion can
succeed while silently omitting critical activation metadata. There is no way to
tell from the stored snapshot whether fields are missing because they were
unavailable or because the capture code failed. A model influencing live decisions
with an incomplete audit trail is a provenance risk.

## Proposed approach

- Collect provenance errors explicitly: each capture block should append to a
  `snapshot_errors` list instead of silently passing. Add `snapshot_complete: bool`
  (True iff `snapshot_errors` is empty) to the promotion log JSON.
- For `PAPER_ACTIVE` transitions, require the following fields to be present before
  writing the promotion log and committing the state change; block the promotion
  (return `{"promoted": False, "error": "incomplete_provenance", ...}`) if any are
  absent and `force=False`:
  - `model_id`
  - `model_version`
  - `training_config_hash`
  - `training_commit_sha` (SHA at train time — stored on `learning_models` or inferred)
  - `activation_commit_sha` (SHA at `promote()` call time — captured at runtime)
  - `strategy_hash`
  - `policy_hash`
  - `policy_version`
  - `evidence_contract_version`
- Distinguish `training_commit_sha` from `activation_commit_sha`: they can
  legitimately differ when code was updated between train and promotion.
- If `learning_models` does not already store `training_commit_sha`, add the column
  in `agent_db.py` and populate it in `ChallengerModel._write()`.
- OBSERVE transitions: record `snapshot_complete`/`snapshot_errors` but do not block.
- Question: should `force=True` bypass the provenance check for PAPER_ACTIVE, or
  should it be a separate `--skip-provenance` flag with an explicit audit note?

## Touches

- `agents/learning/calibration.py` (`promote()`, provenance capture blocks)
- `agent_db.py` (possibly add `training_commit_sha` column to `learning_models`)

## Done when

- [ ] Every provenance capture block in `promote()` appends to `snapshot_errors` on failure rather than silently passing
- [ ] `snapshot_complete` and `snapshot_errors` are present in every `promotion_metrics_snapshot`
- [ ] A `PAPER_ACTIVE` promotion with missing required provenance fields returns `promoted: False` (unless overridden)
- [ ] `training_commit_sha` and `activation_commit_sha` are recorded as distinct fields
- [ ] Existing tests pass; a new test verifies that a PAPER_ACTIVE promotion with missing provenance is blocked
