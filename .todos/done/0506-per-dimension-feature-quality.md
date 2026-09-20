# Per-Dimension Feature Quality: Stability, Evidence, and Attribution Usability

- **ID:** 0506
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0505

## Problem

Engine-level acceptance (macro_validation_status=ACCEPTED) and dimension-level feature quality are different concepts. The live run showed XOM rate/dollar/inflation/geo all stable, while ITOCF/MITSF geopolitical scores were highly variable (stddev 3.0). After engine acceptance, Macro Attribution would still bucket ITOCF geopolitical_risk = 6 (unstable) alongside XOM rate_sensitivity = 7 (stable) as if they carry equal information. Without per-dimension quality flags, an accepted engine still feeds noisy features into formal analysis.

## Proposed approach

Add per-dimension quality metadata to each score, persisted alongside the 1–10 value:

```json
{
  "rate_sensitivity": {
    "score": 7,
    "evidence_quality": "full",
    "stability_class": "stable",
    "usable_for_attribution": true
  },
  "geopolitical_risk": {
    "score": 6,
    "evidence_quality": "limited",
    "stability_class": "unstable",
    "usable_for_attribution": false
  }
}
```

**`stability_class`** derived from live acceptance repeatability stats (persisted per ticker×dim in acceptance record):
- `stable`: stddev ≤ 1.0 in last acceptance run
- `borderline`: stddev 1.0–1.5
- `unstable`: stddev > 1.5
- `untested`: no repeatability data yet (new ticker since acceptance)

**`evidence_quality`** already exists per dimension (from 0476). Map to attribution usability:
- `full` evidence + `stable` → `usable_for_attribution: true`
- `partial` evidence + `stable` → `usable_for_attribution: true` (with note)
- Any `unstable` → `usable_for_attribution: false`
- `unsupported` → `usable_for_attribution: false`
- `untested` → `usable_for_attribution: false` (conservative default)

Store `stability_class` from acceptance run stats in a `macro_dimension_stability` table keyed by `(ticker, dimension, acceptance_record_id)`.

## Touches

- `portfolio_ai.py` — score dict structure; `macro_dimension_stability` table
- `scripts/validate_macro_scorer.py` — persist per-ticker×dim repeatability stats to DB after acceptance run
- `scripts/macro_attribution.py` — filter on `usable_for_attribution=true` per dimension

## Done when

- [ ] Score dict carries per-dimension `stability_class`, `evidence_quality`, `usable_for_attribution`
- [ ] `macro_dimension_stability` table populated after each acceptance run
- [ ] Attribution filters on `usable_for_attribution=true` before bucketing
- [ ] ITOCF/MITSF geopolitical_risk (unstable) excluded from formal attribution buckets
- [ ] XOM rate/dollar/inflation/geo (stable, full evidence) included
