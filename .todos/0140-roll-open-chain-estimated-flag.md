# Fix Roll Outcome estimated Flag for Open Trade Chains

- **ID:** 0140
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

`_compute_cc_management_returns()` (`agents/outcome_evaluator.py` ~lines 273-308) marks a roll outcome as `actual_is_estimated=False` as soon as `exec_rec` is present (i.e., the roll's own BTC and STO legs have known execution prices). But "confirmed" is wrong here: the roll's economic outcome isn't observable until the replacement call reaches a terminal state — either expiring OTM, getting bought back, getting assigned, or being rolled again. If the replacement call is later BTC'd early or rolled again, the stored "confirmed" outcome is incorrect because it assumed hold-to-expiry.

This is the immediate fix subset of 0136 (full multi-hop chain linkage). It doesn't require linking outcomes across the chain — it just prevents premature confirmation.

## Proposed approach

In `_compute_cc_management_returns()`, before returning `(actual_r, agent_r, False)` for an executed roll, query whether the replacement call has an open child in the trade chain:

```python
# In agent_db.py — new helper
def get_open_chain_child(rec_id: int, conn) -> bool:
    """Returns True if rec_id has a child recommendation that is not yet completed."""
    row = conn.execute(
        "SELECT id FROM recommendations WHERE parent_cc_rec_id = ? AND status != 'completed' LIMIT 1",
        (rec_id,),
    ).fetchone()
    return row is not None
```

Then in the evaluator:
```python
# If exec_rec exists but replacement call still has open downstream action:
chain_still_open = agent_db.get_open_chain_child(rec.id, conn)
return actual_r, agent_r, chain_still_open  # estimated=True if chain open
```

Only mark `actual_is_estimated=False` when the chain is in a terminal state (no open child recommendation pointing back to this roll via `parent_cc_rec_id`).

## Touches

- `agents/outcome_evaluator.py` — `_compute_cc_management_returns()` (~lines 273-308): add open-chain check before returning confirmed result
- `agent_db.py` — new `get_open_chain_child(rec_id, conn)` query helper

## Done when

- [ ] An executed roll whose replacement call has a subsequent open action → `actual_is_estimated=True`
- [ ] An executed roll whose replacement call expired OTM (no child) → `actual_is_estimated=False`
- [ ] An executed roll whose replacement was BTC'd (child is completed) → `actual_is_estimated=False`
- [ ] Existing roll outcome tests pass
