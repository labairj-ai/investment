# Adaptive Distribution Scoring for Uncertain Dimensions

- **ID:** 0507
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0506

## Problem

Running N=1 LLM inference and treating the output as an exact structural feature is statistically unjustified for dimensions where the model is known to be variable (limited evidence, foreign companies, geopolitical). But running N=20 for every ticker every week is excessive. The live run showed that well-evidenced domestic companies (XOM) need only N=1, while limited-evidence foreign companies (ITOCF, MITSF) need multiple samples to produce a trustworthy estimate.

## Proposed approach

Adaptive N based on stability class from 0506:

- `stable` (stddev ≤ 1.0): N = 1 (current behavior, no change)
- `borderline` (stddev 1.0–1.5): N = 3
- `unstable` (stddev > 1.5): N = 5
- `untested` (new ticker): N = 3 on first scoring, then classify

Per-dimension, not per-ticker. A ticker could use N=1 for rate_sensitivity (stable) and N=5 for geopolitical_risk (unstable).

Persist distribution metadata alongside the score:
```json
{
  "geopolitical_risk": {
    "score": 6,           // modal/median used as display value
    "median": 6,
    "mean": 5.8,
    "stddev": 1.4,
    "min": 4,
    "max": 8,
    "n_samples": 5,
    "stability_class": "borderline"
  }
}
```

When `stddev > 1.5` after N samples: set `usable_for_attribution = false` regardless of evidence quality (model is not stable enough for this ticker×dim combination at this evidence level).

## Touches

- `portfolio_ai.py` — `generate_holding_macro_scores()` — adaptive N loop per dimension
- Score dict structure — distribution fields alongside point estimate
- Weekly scoring will take longer for uncertain dimensions — acceptable trade-off

## Done when

- [ ] Stable dimensions scored N=1; borderline N=3; unstable N=5
- [ ] Distribution fields (median, mean, stddev, min, max, n_samples) persisted per dimension
- [ ] Display value uses median/modal score, not single inference
- [ ] `usable_for_attribution=false` if post-sampling stddev still > 1.5
- [ ] Total weekly scoring time documented (expected increase for foreign-company portfolios)
