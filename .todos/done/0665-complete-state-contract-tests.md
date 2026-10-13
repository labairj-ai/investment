# Complete State-Contract Test Coverage

- **ID:** 0665
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0658

## Problem

The 8-row state matrix has two issues, and several boundary/edge cases are unexercised:

1. **Duplicate parameter row:** The matrix has two identical `("HEALTHY", None, "STABLE")` rows. One was intended to represent "opportunity-only" but the parametrized test doesn't actually inject an opportunity. The opportunity-only case is covered by a separate `test_healthy_opportunity_only_is_stable()`, but the duplicate row is misleading and the "changes only" case isn't asserted in the matrix.

2. **Missing "changes only" case:** `HEALTHY + changes list only + no attention → STABLE` is not explicitly in the matrix. This is a real boundary: `changes` is a different section from `opportunities` and `attention_items`, so a regression there could produce UNKNOWN rather than STABLE.

3. **Malformed severity not covered:** `severity = None`, `severity = "high"` (string), `severity = -1`, `severity = 9999` — all possible in practice if a news event returns unexpected data. `_derive_portfolio_state()` must handle these without raising.

4. **Multiple attention items where only one crosses 70:** Verify that a single high-severity item in a mixed list is enough to trigger URGENT, not ATTENTION.

5. **`brief_health` missing or garbage:** `brief_health = None`, `brief_health = "GREAT"`, `brief_health = ""` — all should produce UNKNOWN (not STABLE) when there are no attention items.

## Proposed approach

- Remove one of the duplicate `("HEALTHY", None, "STABLE")` parameter rows from the matrix.
- Add `("HEALTHY", "changes-only", "STABLE")` parametrize case — inject a non-empty `changes` field, empty `attention_items`.
- Add `test_healthy_changes_only_is_stable()` (or fold into matrix with a `changes` fixture).
- Add `test_malformed_severity_does_not_raise()` parametrized over `[None, "high", -1, 9999]` — assert no exception and expected state (string/None severity treated as 0, -1 as 0, 9999 as URGENT).
- Add `test_mixed_severity_one_high_triggers_urgent()` — two attention items, severity 50 and 80 → URGENT.
- Add `test_missing_brief_health_is_unknown()` and `test_garbage_brief_health_is_unknown()`.

## Touches

- `tests/test_portfolio_brief.py` — remove duplicate row; add changes-only case; malformed severity tests; mixed-severity test; missing/garbage brief_health tests

## Done when

- [x] No duplicate rows in the parametrized state matrix
- [x] `HEALTHY + changes only + no attention → STABLE` is explicitly asserted
- [x] Malformed severity values (`None`, string, `-1`, `9999`) do not raise; each produces the expected state
- [x] Mixed attention list with one item ≥ 70 → URGENT
- [x] `brief_health = None` → UNKNOWN; `brief_health = "GREAT"` → UNKNOWN
- [x] All new tests pass

## Outcome

State matrix refactored: removed duplicate `("HEALTHY", None, "STABLE")` row; added 4th `has_changes` parameter; row 2 is now `("HEALTHY", None, "STABLE", True)` explicitly testing changes-only. Also added: `test_healthy_changes_only_is_stable` (direct `_derive_portfolio_state` call with changes), `test_malformed_severity_does_not_raise` parametrized over [None, "high", -1, 9999] with correct expected states per `_sev_int` mapping ("high" → 80 → URGENT, not 0), `test_mixed_severity_one_high_triggers_urgent`, `test_missing_brief_health_is_unknown`, `test_garbage_brief_health_is_unknown`. 1670 tests pass.
