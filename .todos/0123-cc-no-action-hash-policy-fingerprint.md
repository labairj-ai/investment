# Add CC Thesis Policy Fingerprint to CC NO ACTION Hash

- **ID:** 0123
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0093

## Problem

The CC agent NO_ACTION hash (`_compute_no_action_state_extras` in `orchestrator.py`) captures market state: IV bucket, spread, open_cc flag, shares bucket, and earnings proximity. It does NOT include a fingerprint of the CC policy stored in the thesis.

The CC policy fields that affect whether the CC agent would recommend a new call:
- `strategy` (INCOME / UPSIDE_PRESERVATION / NONE)
- `max_preferred_delta`
- `minimum_otm_pct`
- `avoid_earnings`
- `preferred_dte_min` / `preferred_dte_max`

If a user changes their delta tolerance from 0.30 to 0.20, or switches strategy from INCOME to UPSIDE_PRESERVATION, or enables `avoid_earnings`, the existing NO_ACTION row will be reused for the next run instead of the CC agent being re-invoked. The stale NO_ACTION will suppress a recommendation that the new policy would have produced.

`THESIS_VERSION` in the orchestrator hash (`_get_thesis_version_for_hash`) would catch thesis changes, but the CC policy can be updated independently of the top-level thesis version if the schema allows it — and even if version increments, the current code doesn't separately identify that the CC policy specifically changed.

## Proposed approach

Add a `cc_policy_hash` key to the CC extras in `_compute_no_action_state_extras`:

```python
import hashlib, json as _json

policy = _get_cc_policy_for_hash(ticker)   # dict of policy fields only
cc_policy_str = _json.dumps(policy, sort_keys=True)
result["cc_policy_hash"] = hashlib.sha256(cc_policy_str.encode()).hexdigest()[:12]
```

Only include the fields that materially change CC selection (strategy, max_preferred_delta, minimum_otm_pct, avoid_earnings, preferred_dte_min, preferred_dte_max). Do not include fields that don't affect candidate selection.

Note: if `cc_policy` is stored as a JSON blob in `investment_theses`, the above can be computed from the stored value without a new helper — just parse, extract the 6 fields, sort-serialize, hash.

## Touches

- `agents/orchestrator.py` (`_compute_no_action_state_extras` for `covered_call`)
- Possibly `agent_db.py` or `covered_call_agent.py` if a helper is factored out
- `tests/test_lifecycle.py` — add test that CC NO_ACTION hash changes when cc_policy strategy changes

## Done when

- [ ] CC NO_ACTION extras include `cc_policy_hash` derived from the 6 policy fields
- [ ] A test confirms the hash changes when `max_preferred_delta` changes in the stored cc_policy
- [ ] A test confirms the hash is stable when cc_policy is unchanged across two consecutive runs
