# Hash Resolved Effective Policy, Not Raw JSON Template

- **ID:** 0323
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** low
- **Depends:** none

## Problem

`policy_hash()` hashes `_raw_json`, which contains unresolved `${ENV_VAR}` placeholders
(e.g. `${ALPACA_PAPER_ACCOUNT_ID}`). Changing `ALPACA_PAPER_ACCOUNT_ID` in the
environment produces an identical hash even though the effective policy is different.
This means the audit trail does not detect env-var substitution changes, and the hash
cannot be used to confirm which account ID was actually authorized for a given cycle.

Must be resolved before a funded (live) account — the hash's purpose is to prove the
policy in effect at execution time.

## Proposed approach

- Hash the **resolved** policy values — the dataclass or dict produced after env-var
  substitution — instead of (or in addition to) `_raw_json`.
- Alternatively, separately record the resolved `account_id` (broker account ID) next to
  the policy hash in every audit row, so a human can verify the right account was
  targeted even if the hash includes raw JSON.
- Open question: should `_raw_json` hash be preserved alongside for template-change
  detection, or replaced entirely?

## Touches

- `trade_engine/policy.py` (or wherever `policy_hash()` lives) — hash resolved values
- Any audit-record writers that call `policy_hash()`

## Done when

- [x] `policy_hash()` (or its replacement) produces different output when only an env-var substitution changes
- [x] Audit rows include either a resolved-policy hash or the resolved `account_id` field
- [x] Existing tests updated to match new hash semantics

## Outcome

policy_hash() now serializes resolved dataclass fields (circuit_breakers already has env vars substituted) via json.dumps(sort_keys=True) instead of raw _raw_json. Changing ALPACA_PAPER_ACCOUNT_ID env var now changes the hash. 718 tests pass.
