# Sell/Trim Formula Calibration Audit

- **ID:** 0188
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

The `SellStrength = 0.40*T + 0.20*F + 0.15*V + 0.15*P + 0.10*O` formula was designed before Decision Quality data existed. The weights have never been calibrated against actual realized outcomes — they reflect an informed prior, not empirical validation. The reviewer specifically asked whether these weights are defensible and what the correct calibration looks like.

Open questions from the reviewer:

**1. Is 40% T weight right?**
T (thesis deterioration) dominates the formula: a T=75 position (severe thesis break) produces ss=30 at the SellStrength boundary just from T alone, before F/V/P/O are even considered. Is 40% appropriate for cases where the thesis break is mild but valuation is extreme or the position is very concentrated?

**2. Should O (opportunity cost) have more than 10%?**
O currently represents the gap between the held position and the best candidate in the universe. At 10% weight, a universe candidate scoring 95 vs a held position at 0 adds only 9.5 to ss — not enough to push a mildly-declining position into TRIM on its own. Should O be 15–20%?

**3. How should conviction influence the threshold?**
Currently, conviction (stored in the thesis but not used by _score_T or _action_from_strength) has no effect on the SellStrength bands. A position in which conviction=5 (highest) has the same EXIT threshold as conviction=2. Should high-conviction positions require a higher ss before triggering? E.g., `EXIT_THRESHOLD = 68 + 5*(conviction - 3)` so conviction=5 → EXIT at ss=78.

**4. Are the YoY/TTM deterioration thresholds calibrated?**
`_score_F` awards:
- 40 for revenue decline >20% (severe)
- 30 for >10% decline
- 20 for >5% decline
- 15 for flat/declining

For a high-growth SaaS stock, 10% revenue decline might be catastrophic. For a utility, it might be noise. The thresholds are currently static. Should F incorporate sector context or thesis growth expectations?

**5. Critical pillar violation bypass**
Currently, a critical pillar violation sets T = max(T, 90) but still runs the composite. The `_run()` function then forces `suggested = "EXIT"` regardless of ss. Is a hard bypass of the ss composite correct, or should the override be a floor (e.g., ss = max(ss, 80)) that still allows the LLM to say REVIEW vs EXIT?

## Proposed approach

This is a calibration and design review, not a pure code change. Proposed steps:

1. **Query Decision Quality outcomes** for `sell_trim` actions (`actual_is_estimated=0, horizon >= 90 days`) once sufficient data exists (currently gated). Note which actions outperformed the hold benchmark.

2. **Revisit T weight vs O weight**: consider increasing O from 0.10 to 0.15 and reducing P from 0.15 to 0.10 — this makes opportunity cost as significant as concentration.

3. **Add conviction multiplier to action thresholds**: apply `EXIT_THRESHOLD = max(55, 68 - 4*(conviction - 3))` for conviction below 3 (lower bar to exit low-conviction positions) and `EXIT_THRESHOLD = min(80, 68 + 4*(conviction - 3))` for conviction above 3.

4. **Make F deterioration thresholds configurable** from `strategy.json` so they can be tuned without code changes.

5. **Revisit critical pillar bypass**: currently it hard-forces EXIT. Consider a graduated response: critical violation + 1 other signal → EXIT, critical violation alone → REVIEW_EXIT (similar to the existing REVIEW band) with a flag in the payload.

## Touches

- `agents/sell_trim_agent.py` — `_action_from_strength()`, `_score_F()` thresholds, `_score_T()` critical bypass
- `strategy_config.py` or `config/strategy.json` — optionally externalize F thresholds
- `tests/test_sell_trim_agent.py` or similar — update/add tests for modified thresholds

## Done when

- [ ] DQ data query path is documented (even if not yet executable due to sample size gate)
- [ ] Conviction influence on EXIT threshold is at minimum evaluated and either implemented or explicitly rejected with a documented reason
- [ ] O weight vs P weight reconsideration is evaluated
- [ ] F deterioration thresholds are reviewed against thesis growth expectations (sector-neutral or configurable)
- [ ] Critical pillar bypass behavior is explicitly confirmed or revised
- [ ] If any weights/thresholds are changed, existing SellStrength tests pass and the change is documented in the formula comment at the top of sell_trim_agent.py
