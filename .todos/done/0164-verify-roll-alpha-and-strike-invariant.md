# Add Explicit Tests for Roll Alpha Benchmark and ROLL_UP Strike Invariant

- **ID:** 0164
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

The reviewer flagged two recent changes as "not verifiable from current extracted view" / "keep under review":

1. **Roll alpha benchmark (0153)**: `_suggest_next_call()` was updated to rank by `(new_cc_alpha - existing_alpha) / nav` where `existing_alpha = mark - E[max(S_T-K_old,0)]`. No targeted test exists that verifies a deep-ITM existing call (expected payoff > mark) is correctly recognized as a liability and produces a positive incremental score for rolling.

2. **ROLL_UP strike invariant (0156)**: `_suggest_next_call()` rejects candidates with `strike <= existing_strike` for ROLL_UP/ROLL_UP_AND_OUT. No test exercises the case where a caller accidentally passes a low `min_strike` and confirms the guard catches it.

Without these tests, regressions in either guard would not be caught automatically.

## Proposed approach

Add to `tests/test_covered_call_rec.py` (create if absent, or add to `test_covered_call_agent.py`):

**Roll alpha tests (unit — no yfinance, use a mock stock):**
- Build a synthetic candidate where `new_cc_alpha = $2`, `existing_call_mark = $5`, `existing_expiry_date` 30 days out, `existing_strike` deep ITM → `expected_old_payoff > $5` → `existing_alpha < 0` → `score > 0` (roll is attractive). Confirm the candidate is selected.
- Contrast with OTM existing call where `existing_alpha > 0` → score is lower, candidate may be rejected.

**Strike invariant tests (unit):**
- ROLL_UP with `existing_strike=150`, candidates at $148, $150, $155 → only $155 selected.
- ROLL_UP_AND_OUT same setup → same guard applies.
- ROLL_OUT with same candidates → $148 and $150 not rejected by strike guard.

## Touches

- `tests/test_covered_call_rec.py` (create if absent) or `tests/test_covered_call_agent.py` — new test class/functions for both guards
- No production code changes; tests only

## Done when

- [ ] Deep-ITM existing call → positive incremental score → roll candidate accepted (test passes)
- [ ] OTM existing call with negative-alpha new candidate → rejected (test passes)
- [ ] ROLL_UP candidate at same or lower strike → filtered out (test passes)
- [ ] ROLL_OUT does not apply the strike guard (test passes)
- [ ] `python -m pytest tests/ -v` passes with no regressions
