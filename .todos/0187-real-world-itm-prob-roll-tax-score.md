# Real-World ITM Probability in Roll Tax Score Component

- **ID:** 0187
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

The roll candidate tax score component introduced in 0182 uses option delta as a proxy for assignment probability:
```python
tax_component = tax_benefit_per_share * d / nav
```
Delta (`d`) is the risk-neutral probability of expiring ITM — it answers "what does the options market imply?" not "what actually happens in real portfolios?" Risk-neutral pricing embeds a variance risk premium, so delta systematically overstates real-world assignment probability for out-of-the-money candidates.

The codebase already has a real-world ITM probability framework used by `expected_upside_lost()` via `_real_world_itm_prob()` or the equivalent call inside `expected_upside_lost`. That function uses the drift model with `mu = RISK_FREE_RATE` (or a user-specified real-world drift) and `lognormal CDF` to compute `P(S_T > K)` under a real-world measure.

## Proposed approach

1. Extract or expose a helper `_real_world_itm_prob(S, K, T, sigma, mu)` from the existing `expected_upside_lost()` machinery. This is likely already computed there; the function just needs to return it (or a version of it).

2. In `_suggest_next_call()`, compute `rw_prob = _real_world_itm_prob(current_price, s, T, sigma, mu)` for each candidate.

3. Replace `d` (delta) with `rw_prob` in the tax component:
   ```python
   tax_component = tax_benefit_per_share * rw_prob / nav
   ```

4. If `_real_world_itm_prob()` isn't already exposed as a standalone function, add it to `covered_call_rec.py`. The required inputs (`current_price`, `s`, `T`, `sigma`, `mu`) are all already in scope inside the candidate loop.

**Note:** keep `d` (delta) in the delta eligibility filter `0.15 <= d <= 0.40` — delta is the right filter for option market liquidity/characteristics. Only replace delta as the probability weight in the tax component.

## Touches

- `covered_call_rec.py` — `_suggest_next_call()` tax_component line; possibly add `_real_world_itm_prob()` helper
- `tests/test_cc_management.py` — verify tax component uses real-world prob, not delta, for an OTM candidate where the two differ

## Done when

- [ ] `_real_world_itm_prob(S, K, T, sigma, mu)` available as a callable
- [ ] `_suggest_next_call()` uses `rw_prob` instead of `d` for `tax_component`
- [ ] Delta still used for eligibility filtering
- [ ] Test: OTM candidate where delta=0.20 and rw_prob=0.12 → tax_component uses 0.12
- [ ] All existing tests pass
