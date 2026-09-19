# Make Acceptance Activation Transactional

- **ID:** 0523
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0517, 0519

## Problem

The validator currently writes the acceptance artifact and then attempts to persist `macro_dimension_validation` rows in a separate step. A database lock causes the persistence to fail silently with a warning. `macro_acceptance_state` is not updated atomically with the dimension rows — so a PASS can leave half-committed state: artifact written, DB rows missing, old acceptance still active, requiring manual repair. For a system controlling autonomous investment decisions, half-committed validation state is not acceptable.

## Proposed approach

In `scripts/validate_macro_scorer.py`, after the verdict is determined, replace the current catch-and-warn persistence block with a single atomic activation:

1. Open a SQLite connection with `timeout=60` to survive momentary service locks
2. `BEGIN IMMEDIATE` transaction
3. `INSERT OR IGNORE` all `macro_dimension_validation` rows (PASS only)
4. `INSERT OR REPLACE INTO macro_acceptance_state` (record_id, commit_sha, model_identity, notes)
5. `COMMIT` — print "activated: true" on success
6. On any exception: `ROLLBACK`, keep the previous acceptance authoritative, print the error, `sys.exit(1)`

Add a bounded retry (3 attempts, 10s sleep) before giving up so a transient lock does not destroy the run.

Add `activated: true/false` to the acceptance JSON artifact so a PASS run whose activation failed is distinguishable from a fully committed acceptance. The JSON artifact is always written regardless of DB outcome — it is evidence.

## Touches

- `scripts/validate_macro_scorer.py` — persistence block replaced with atomic transaction + bounded retry
- Acceptance JSON output: add `activated` boolean field

## Done when

- [ ] Single `BEGIN IMMEDIATE` transaction covers both `macro_dimension_validation` inserts and `macro_acceptance_state` upsert
- [ ] Any failure rolls back completely; old acceptance remains active; process exits non-zero
- [ ] `activated: true/false` field appears in acceptance JSON artifact
- [ ] Bounded retry (≤3 attempts, 10s sleep) before giving up on transient lock
- [ ] No manual SQL required for a successful PASS run to become the active acceptance
