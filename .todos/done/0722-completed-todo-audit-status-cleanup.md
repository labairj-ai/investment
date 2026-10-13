# Normalize Completed TODO Status Metadata and Audit Trail

- **ID:** 0722
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** normal
- **Depends:** none

## Problem

Several completed CC TODO files under `.todos/done/` still contain `**Status:** done` even though their implementations are on `main`.

This does not affect runtime behavior, but it weakens the repository audit trail and makes automated status reporting ambiguous.

## Proposed approach

Normalize completed TODO metadata.

For each file under `.todos/done/`:

- set `Status` to the repository's canonical completed value;
- preserve ID, title, creation date, priority, dependencies, problem statement, and acceptance history;
- do not rewrite substantive task requirements after completion;
- optionally append standard completion metadata if the repo supports it.

At minimum inspect/fix 0711–0716.

Add a lightweight consistency check:

- files under `.todos/done/` cannot declare open-state status;
- open `.todos/*.md` cannot declare completed state unless intentionally archived immediately.

## Implementation guardrails

- Metadata/audit cleanup only.
- No production-code behavior changes.
- Do not alter historical acceptance requirements.
- Do not mark actually incomplete work complete merely because it sits in the wrong folder.
- Investigate folder/status disagreements before changing metadata.
- Preserve Git history as implementation provenance.

## Touches

- `.todos/done/*.md`
- optional TODO consistency checker
- tests if checker is added

## Acceptance tests

- [ ] 0711–0716 no longer show open-state status if verified complete.
- [ ] Canonical completed status is consistent.
- [ ] IDs/titles/dependencies remain unchanged.
- [ ] No substantive requirement text is removed.
- [ ] Done-folder file with `Status: backlog` is flagged.
- [ ] Done-folder file with completed status passes.
- [ ] Open TODO marked completed is flagged.
- [ ] Non-TODO Markdown is ignored.

## QA requirements

- [ ] Scan all `.todos/done/*.md` for open-state statuses.
- [ ] Scan open `.todos/*.md` for completed-state statuses.
- [ ] Manually verify every mismatch before bulk edit.
- [ ] If checker is added, run it in CI with fixture tests for both mismatch directions.
- [ ] Confirm application tests/runtime artifacts are unchanged.

## Done when

- [ ] Completed TODO metadata matches completed-folder state
- [ ] Open TODO metadata matches open-folder state
- [ ] Future status/folder drift is detected or explicitly documented
