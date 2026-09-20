# Give Acceptance Records Immutable UUIDs, Fail on Duplicates

- **ID:** 0533
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** none

## Problem

Formal validation currently uses the output file path as `record_id` and writes rows with `INSERT OR IGNORE`, so re-running with the same `--out` path silently leaves old DB rows attached to a newly overwritten JSON artifact. The DB record and the artifact on disk can diverge without any error. An acceptance system that allows silent no-ops on duplicate IDs cannot guarantee that what the DB says was accepted matches what is actually in the artifact.

## Proposed approach

- Generate `record_id` as a UUID (e.g. `uuid.uuid4()`) or a content-addressed hash of the run inputs at the start of each acceptance attempt, independent of the output path.
- Replace `INSERT OR IGNORE` with a plain `INSERT`; a constraint violation on a duplicate ID should raise a fatal error and abort the run.
- Store the output path as a separate provenance field (not the primary key) so reruns to the same path are detectable.
- Add a test that attempts to write two acceptance records with the same ID and asserts a hard failure (not silent ignore).

Open question: content-addressed ID (hash of ticker set + config hash + timestamp) vs. pure UUID — UUID is simpler but content-addressed makes the ID auditable. Either works; just pick one consistently.

## Touches

- `validate_macro_scorer.py` (record_id generation, DB write path)
- DB schema migration (record_id column semantics; add output_path as separate provenance column if not already present)
- Test suite (duplicate-ID failure test)

## Done when

- [ ] `record_id` is a UUID or content-addressed value generated at run start, not derived from the output path
- [ ] Duplicate `record_id` on insert raises a fatal error; `INSERT OR IGNORE` is gone from the acceptance write path
- [ ] Output path is stored as a separate provenance field
- [ ] Test confirms a duplicate ID attempt terminates with an error rather than silently succeeding

## Review — 2026-09-20

Partially implemented in 4dbb0c0. UUIDs, plain dimension-row INSERTs, and separate artifact output_path are implemented. The UUID is generated after validation rather than at run start. The duplicate test exercises raw SQL rather than the acceptance write path; finish run-start identity and verify duplicate failure through that path before closing.
