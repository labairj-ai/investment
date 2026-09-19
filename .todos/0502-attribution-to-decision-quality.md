# Attribution to Actual Decision Quality: Base vs Challenger Divergence

- **ID:** 0502
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0501

## Problem

Macro Attribution V1 and V2 ask: do macro variables correlate with future alpha? That's useful but not the most actionable question. The more important question for the Learning Lab is: when base and challenger diverge in their recommendation, are macro conditions associated with which one wins? That directly links Macro Risk to decision quality without giving it ranking authority.

## Proposed approach

This todo activates only when 0501 is complete and there are ≥30 ACCEPTED episodes where base and challenger made different recommendations (divergent episodes).

Add a `divergence_analysis` section to `scripts/macro_attribution.py`:
1. Filter to episodes where challenger recommendation ≠ base recommendation
2. For divergent episodes, group by macro regime at decision time (e.g. rate_stress > 0 vs ≤ 0)
3. Compare challenger win rate (challenger alpha > base alpha) across macro regime groups
4. Separately: for episodes where the structural score disagreed with the factor beta (concordance_ok = false), what was the challenger win rate?

This is still purely descriptive — no model fitting, no weight adjustment. Goal: a falsifiable test. If macro conditions are associated with which system wins divergent calls, that's meaningful evidence. If there's no signal, that's also meaningful — it rules out macro as a useful feature for challenger design.

Output: `divergence_analysis` section in `out/macro_attribution_TIMESTAMP.json` with: n_divergent, regime_group_win_rates, concordance_group_win_rates, and a plain-language observation.

## Touches

- `scripts/macro_attribution.py` — `divergence_analysis` section
- Requires: decision_episodes with macro_snapshot + outcome + challenger/base recommendation stored

## Done when

- [ ] Runs only when ≥30 divergent ACCEPTED episodes with 3m outcomes exist
- [ ] Challenger win rate compared across macro regime groups
- [ ] Concordance group (agreed vs disagreed beta/LLM) compared
- [ ] Output is descriptive only — no weights changed, no ranking affected
- [ ] Plain-language observation written to output explaining what the data shows
