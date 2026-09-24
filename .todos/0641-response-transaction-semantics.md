# Harden apply_brief_response Transaction Semantics

- **ID:** 0641
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0639

## Problem

`apply_brief_response()` ends with `conn.commit()`, which makes it own the caller's transaction. A caller that has an uncommitted write on the same connection will have that write committed without intending to. The function should guarantee atomicity of its own INSERT without committing a broader caller transaction. Additionally, action-vocabulary validation (`action not in {"REVIEW", "DISMISS", "DEFER"}`) happens only in the HTTP handler; a non-HTTP internal caller can insert arbitrary action values. SAVEPOINT cleanup also has the same issue as 0639: `ROLLBACK TO` without a subsequent `RELEASE` leaves a dangling savepoint.

## Proposed approach

- Remove the unconditional `conn.commit()` from `apply_brief_response()`. The function wraps its own INSERT in a SAVEPOINT for atomicity; callers who want to commit the outer transaction can do so themselves.
- Move action-vocabulary validation (`{"REVIEW", "DISMISS", "DEFER"}`) inside `apply_brief_response()` so it's enforced regardless of call site.
- After `ROLLBACK TO SAVEPOINT brief_respond`, add `RELEASE SAVEPOINT brief_respond`.
- Update the HTTP handler to call `conn.commit()` explicitly after `apply_brief_response()` returns success.
- Add a test: create an uncommitted row, call `apply_brief_response()`, confirm the response was recorded but the unrelated row is still uncommitted.

## Touches

- `portfolio_ai.py` — `apply_brief_response()` (remove commit, add action validation, fix ROLLBACK/RELEASE)
- `serve.py` — `_handle_brief_respond()` (add explicit `conn.commit()` after success)
- `tests/test_portfolio_brief.py` — caller-transaction-survival test; invalid action → 400 test

## Done when

- [ ] `apply_brief_response()` contains no `conn.commit()` call
- [ ] Action vocabulary is validated inside `apply_brief_response()`; invalid action returns 400
- [ ] `ROLLBACK TO SAVEPOINT` is followed by `RELEASE SAVEPOINT`
- [ ] Test proves: an uncommitted caller write on the same connection survives a successful `apply_brief_response()` call (is not auto-committed)
- [ ] HTTP handler commits explicitly after `apply_brief_response()` returns 200
