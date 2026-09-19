# Acceptance-Scoped Usability: Tie _is_formally_usable to Active Acceptance Record

- **ID:** 0519
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0517, 0518

## Problem

`_is_formally_usable(ticker, dim, conn)` queries `macro_dimension_validation` (after 0517) for any row where `validation_run_type = 'accepted_validation'`. It does not verify that the row's `acceptance_record_id` matches the currently active `macro_acceptance_state.record_id`. If the validator is re-run (e.g. on a new model or config), the old acceptance record is superseded — but the old validation rows remain in the table. Until 0517 is done, a scorer running after a second PASS acceptance would find rows from both validation runs, and `_is_formally_usable()` would return True based on stale evidence from the superseded contract.

The fix ties the usability gate to the currently active contract, not to any historical accepted row.

## Proposed approach

`_is_formally_usable()` must:
1. Look up `macro_acceptance_state` to get the active `record_id` (if none, return False immediately)
2. Join to `macro_dimension_validation` on `acceptance_record_id = <active_record_id>`

```python
def _is_formally_usable(ticker, dim, conn):
    row = conn.execute(
        "SELECT record_id FROM macro_acceptance_state WHERE validation_name=? AND status='ACCEPTED' ORDER BY accepted_at DESC LIMIT 1",
        ("macro_validation_v1",)
    ).fetchone()
    if not row:
        return False
    active_record_id = row[0]
    result = conn.execute(
        """SELECT stability_class FROM macro_dimension_validation
           WHERE acceptance_record_id=? AND ticker=? AND dimension=?""",
        (active_record_id, ticker, dim)
    ).fetchone()
    return result is not None
```

This means: if the validation was re-run with a new config or model, scores from the old acceptance run are no longer formally usable until re-scored under the new contract. This is the correct behavior — formal usability is relative to the active contract, not any historical one.

**`generate_holding_macro_scores()`** calls `_is_formally_usable()` per dimension per ticker to set `{dim}_usable_for_attribution`. After this fix, the value will be False for any ticker/dim combination that does not appear in the current acceptance run's validation rows.

Note: `_is_formally_usable()` returning False does not prevent scoring — it only affects whether the dimension's output flows through to formal Learning Lab attribution.

## Touches

- `portfolio_ai.py` — `_is_formally_usable()` only; no other logic changes required

## Done when

- [ ] `_is_formally_usable()` reads active `record_id` from `macro_acceptance_state` first
- [ ] If no ACCEPTED state exists, returns False immediately
- [ ] Usability query joins on `acceptance_record_id = <active_record_id>`
- [ ] Old acceptance rows from superseded contracts do not make dimensions "usable"
- [ ] Behavior verified: re-running validator with a new config correctly invalidates prior usability
