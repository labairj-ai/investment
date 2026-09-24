# Make Brief State Collection Transaction-Neutral

- **ID:** 0639
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** none

## Problem

`build_portfolio_brief_state()` calls `conn.commit()` before the SAVEPOINT in `create_portfolio_brief()` is created. This silently commits any uncommitted caller write and persists `portfolio_brief_snapshots` before `ai_insights` and `portfolio_brief_provenance` exist. If provenance persistence later fails, `ai_insights` rolls back but `portfolio_brief_snapshots` has already advanced — so the next brief's "changes since last brief" is computed relative to a brief that never successfully existed.

Additionally, `ROLLBACK TO SAVEPOINT` rewinds but doesn't remove the savepoint; it must be followed by `RELEASE SAVEPOINT`. If the `SAVEPOINT` creation itself throws, a subsequent `ROLLBACK TO` will throw a second exception, masking the original.

## Proposed approach

- Remove all `conn.commit()` calls from `build_portfolio_brief_state()`. State collection must be read-only: no writes, no commits.
- Move the `portfolio_brief_snapshots` INSERT and DELETE into the same SAVEPOINT block as `ai_insights` and `portfolio_brief_provenance` inside `create_portfolio_brief()`. All three succeed or all three roll back.
- After `ROLLBACK TO SAVEPOINT brief_write`, add `RELEASE SAVEPOINT brief_write` to drop the savepoint.
- Guard the SAVEPOINT creation so an exception there doesn't cause a secondary exception from the ROLLBACK TO path.
- Apply the same cleanup discipline to `apply_brief_response()` (in `portfolio_ai.py`).

## Touches

- `portfolio_ai.py` — `build_portfolio_brief_state()` (remove commits), `create_portfolio_brief()` (fold snapshot write into SAVEPOINT, tighten ROLLBACK/RELEASE)
- `tests/test_portfolio_brief.py` — add test: seed uncommitted row, call `create_portfolio_brief()`, fail provenance, assert uncommitted row survives and all three brief artifacts (snapshots, ai_insights, provenance) are absent

## Done when

- [ ] `build_portfolio_brief_state()` contains no `conn.commit()` calls
- [ ] `portfolio_brief_snapshots`, `ai_insights`, and `portfolio_brief_provenance` all live inside the same SAVEPOINT; a simulated provenance failure rolls back all three
- [ ] `ROLLBACK TO SAVEPOINT` is always followed by `RELEASE SAVEPOINT`
- [ ] Test proves: an uncommitted caller write survives a failed `create_portfolio_brief()`, and none of the three brief artifacts are present after failure
