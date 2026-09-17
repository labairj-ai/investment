# Fix Dashboard Context: Pass Expiry, Contracts, and Policy

- **ID:** 0174
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`evaluate_open_position()` calls `_build_mgmt_context_from_db()` without passing `expiry`, `contracts`, or `policy` (covered_call_rec.py ~line 1459–1470). As a result:

1. **Tax disposal date falls back to today** — even though 0168 added the `expiry` kwarg, the dashboard never passes it, so `_lot_tax_friction()` still uses `date.today()` as the disposal date, defeating the fix.
2. **Contracts defaults to 1** — multi-contract positions understate friction by `actual_contracts` × the per-contract error.
3. **Assignment policy is empty** — `preserve_high_conviction`, `only_if_overweight`, and all other thesis assignment rules are silently skipped on the dashboard path.

The agent path (`_analyze_roll()`) correctly passes all three. Both paths call the same pure `evaluate_cc_management_state()`, but they feed it different contexts — causing agent ≠ dashboard disagreement even on identical positions.

## Proposed approach

In `evaluate_open_position()`, load the ticker's CC policy and pass it (along with `expiry` and `contracts`) to `_build_mgmt_context_from_db()`:

```python
from agents.covered_call_agent import _get_cc_policy   # or inline the DB call
_policy = _get_cc_policy(ticker)
contracts = position.get("contracts", 1)   # passed in or fetched from cc_positions

_mgmt_ctx = _build_mgmt_context_from_db(
    ticker=ticker,
    current_price=current_price,
    strike=strike,
    dte=dte,
    ...,
    expiry=expiry,
    contracts=contracts,
    policy=_policy,
)
```

If `_get_cc_policy` creates a circular import, inline the `config/cc_policies.json` read directly in `evaluate_open_position()`.

Also audit the caller side: `serve.py` calls `evaluate_open_position()` — ensure it passes `contracts` from the `cc_positions` row if available.

## Touches

- `covered_call_rec.py` — `evaluate_open_position()` call to `_build_mgmt_context_from_db()`
- `serve.py` — `cc-evaluate` endpoint that calls `evaluate_open_position()`
- `agents/covered_call_agent.py` — check for import reuse vs inline

## Done when

- [ ] `evaluate_open_position()` passes `expiry`, `contracts`, and `policy` to `_build_mgmt_context_from_db()`
- [ ] Dashboard tax friction uses expiry as disposal_date, not today
- [ ] Dashboard applies the same assignment policy gates as the agent
- [ ] Test: dashboard and agent paths produce identical `ManagementPolicyContext` for the same inputs
