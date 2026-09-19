# Learning Lab Macro Attribution Analysis

- **ID:** 0495
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0494

## Problem

Once decision episodes carry macro snapshots and outcomes accumulate, the question becomes: do macro variables actually explain anything out of sample? This is an analysis task, not a feature. Answering it requires prospective data — episodes captured after 0494 is active — not retrofitting macro context onto old episodes. The goal is evidence, not modeling: does knowing macro context at decision time predict future alpha, MAE/MFE, or challenger-vs-base outcome?

## Proposed approach

Add a `macro_attribution` analysis module (script or Learning Lab tab section) that runs after sufficient episode accumulation (suggest minimum 60 resolved episodes with macro snapshots):

1. **Simple factor analysis**: group episodes by macro regime bucket (e.g. rate_stress > 0.3 vs ≤ 0.3) and compare mean alpha / outcome rates. No model — just conditional means and counts.
2. **Structural exposure correlation**: compare holding rate_sensitivity scores against episode-level alpha when rate_stress was high. Does high sensitivity → worse alpha when rates were rising?
3. **Concordance check**: do holdings where the LLM score and beta agreed (from 0483 concordance logic) produce more reliable outcomes than ones where they disagreed?
4. **UNKNOWN penalty test**: do episodes with macro_supported=false or UNKNOWN regime show different outcome distributions? (Tests whether unknown data should be treated as neutral or should exclude a holding from certain systems.)

Output: a human-readable summary report in the Learning Lab tab and `out/macro_attribution_YYYYMMDD.json`. Do not build a model yet. Do not update challenger weights or rankings. Findings should inform whether a macro challenger is worth building.

## Touches

- `portfolio_ai.py` or new `macro_attribution.py` — analysis functions
- Learning Lab tab in `generate_dashboard.py` — attribution section (read-only)
- `out/macro_attribution_YYYYMMDD.json` — analysis output

## Done when

- [ ] At least 60 resolved decision episodes have `macro_snapshot` data (from 0494)
- [ ] Conditional mean alpha by regime bucket computed and displayed
- [ ] Structural exposure vs outcome correlation reported (no model, just correlation + N)
- [ ] Concordance vs outcome comparison included
- [ ] Results are clearly labelled as exploratory — no ranking or weight changes
- [ ] Output written to `out/macro_attribution_YYYYMMDD.json`
