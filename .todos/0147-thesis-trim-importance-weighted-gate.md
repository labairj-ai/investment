# Thesis TRIM Gate: Weight Violations by Pillar Importance

- **ID:** 0147
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

The TRIM rule in `run_thesis_monitor()` fires when `composite >= 50 AND any_violated` (~line 533). `any_violated` is True even when a single low-importance pillar (e.g., 5% weight) is violated. This means a supporting pillar violation — one the thesis would survive — generates the same TRIM recommendation as a core-pillar violation. The signal is noisy: TRIM should reflect meaningful thesis stress, not just any violation.

## Proposed approach

Replace `any_violated` with `violated_weight_fraction > threshold`:

```python
total_weight = sum(p["importance"] for p in updated_pillars)
violated_weight = sum(
    p["importance"] for p in updated_pillars if p["det_status"] == "VIOLATED"
)
violated_fraction = violated_weight / total_weight if total_weight > 0 else 0
```

Use `violated_fraction > 0.20` (i.e., >20% of thesis weight is in a violated pillar) as the TRIM gate. This means:
- A 5%-weight pillar violated → violated_fraction = 0.05 → no TRIM
- A 25%-weight pillar violated → violated_fraction = 0.25 → TRIM fires
- Two 15%-weight pillars violated → violated_fraction = 0.30 → TRIM fires

Also add `"violated_weight_fraction": round(violated_fraction, 2)` to the TRIM rec `action_payload`.

## Touches

- `agents/thesis_agent.py` — TRIM rule block (~lines 532-559): replace `any_violated` with weight-fraction gate
- No DB changes needed

## Done when

- [ ] A single 5%-weight pillar violation does not trigger TRIM
- [ ] A 25%-weight pillar violation triggers TRIM when composite is in the 50-65 band
- [ ] `action_payload["violated_weight_fraction"]` is set on TRIM recs
- [ ] Existing tests pass
