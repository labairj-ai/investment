# Normalize Tax Benefit into Roll Ranking Score

- **ID:** 0182
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0181

## Problem

Tax benefit is currently used only as a tiebreaker when two candidates score within 0.001 of each other. That means a candidate saving $4,000 in taxes loses to a candidate with a marginally higher alpha score — even though the after-tax expected value clearly favors the tax-saving candidate.

The root issue is that the primary score (`(cc_alpha − existing_alpha) / nav`) is in per-share normalized units, while tax benefit is in raw dollars. Adding them directly is apples-to-oranges, so the current code deferred it to a tiebreaker. But the right fix is to normalize tax benefit into the same per-share units and weight it by assignment probability before adding it to score.

## Proposed approach

1. Derive total allocated shares from `lot_schedule` (sum of `allocated_shares` entries). This avoids adding a new parameter.

2. Compute per-share, probability-weighted tax benefit:
   ```python
   total_shares = sum(float(e["allocated_shares"]) for e in lot_schedule) or 1.0
   tax_benefit_per_share = tax_benefit / total_shares          # same units as cc_alpha
   weighted_tax = tax_benefit_per_share * d                    # d = candidate delta ≈ assignment prob
   tax_component = weighted_tax / nav if nav > 0.01 else 0.0  # normalized like score
   ```

3. Add `tax_component` to `score` rather than using a separate tiebreaker:
   ```python
   score = (cc_alpha - _existing_alpha) / nav + tax_component
   ```

4. Remove the `abs(score - best["_score"]) < 0.001` tiebreaker block; simple `score > best["_score"]` is sufficient once tax is in the score.

5. Keep `tax_benefit_at_expiry` (raw dollars) in the returned dict for transparency on the dashboard.

**Important counterpoint noted by reviewer:** delta as a proxy for assignment probability is a rough approximation. A future improvement could use the real-world ITM probability from the drift model instead of delta (risk-neutral), but delta is acceptable as a first step.

## Touches

- `covered_call_rec.py` — `_suggest_next_call()` scoring block (lines ~1402–1425)
- `tests/test_cc_management.py` — test: candidate B saves $4,000 in taxes and wins over candidate A with marginally higher raw alpha

## Done when

- [ ] Tax benefit is normalized to per-share, prob-weighted units and added directly to score
- [ ] Tiebreaker replaced by straight score comparison
- [ ] Test: high-tax-benefit candidate wins even when raw alpha is slightly lower
- [ ] `tax_benefit_at_expiry` still present in returned dict
- [ ] All existing tests pass
