# Recursive Multi-Hop Roll Chain Resolution

- **ID:** 0173
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** low
- **Depends:** none

## Problem

When `evaluate_cc_management_state()` recommends ROLL, it evaluates only the immediate candidate (next expiry / adjusted strike). It does not check whether the rolled-into position will itself be eligible for assignment or require another roll. In practice, a chain of two or three rolls is sometimes needed before an assignment-eligible strike/expiry exists, and the agent cannot currently surface this multi-hop path to the user.

This is a deferred enhancement — single-hop ROLL is correct and complete for the current use case. Multi-hop is only needed when the dashboard needs to answer "how many rolls until assignment?"

## Proposed approach

Add an optional `max_hops: int = 1` parameter to `evaluate_cc_management_state()`. When `max_hops > 1` and the result is ROLL, recurse with the roll target as the new `ManagementPolicyContext` (caller must supply candidate context for each hop, or the function must generate candidates internally). Stop at first ALLOW_ASSIGNMENT or when `max_hops` is exhausted.

Open question: whether context generation (fetching strike chain, pricing each candidate) belongs inside `evaluate_cc_management_state()` (breaks purity) or in the caller (agent assembles candidate list first). Lean toward caller-assembles to keep the engine pure.

This todo should not be started until 0168 and 0169 are complete, as the per-lot schedule (0169) is needed to accurately project friction across roll hops.

## Touches

- `covered_call_rec.py` — `evaluate_cc_management_state()` optional recursion
- `agents/covered_call_agent.py` — candidate context generation for multi-hop
- `tests/test_cc_management.py` — test: two-hop roll chain terminates at ALLOW_ASSIGNMENT

## Done when

- [ ] `evaluate_cc_management_state(ctx, max_hops=2)` returns a roll chain of up to 2 hops
- [ ] Engine stays pure (no DB calls inside recursion)
- [ ] Test: chain of [ROLL, ROLL, ALLOW_ASSIGNMENT] with max_hops=3
- [ ] All existing single-hop tests pass unchanged
