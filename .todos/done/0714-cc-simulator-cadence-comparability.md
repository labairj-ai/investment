# Validate CC Simulator Cadence Comparability

- **ID:** 0714
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0707, 0713

## Problem

The prospective virtual book evaluates every 30 minutes during market hours, while historical actual covered-call management may have run on a different cadence. A simulator that observes the market more frequently has more opportunities to trigger delta, premium-capture, roll, and event rules — creating apparent policy disagreement that is caused by observation frequency rather than any difference in policy logic.

## Proposed approach

Add a cadence-comparability layer to simulator validation:

- For each actual/virtual management opportunity persist: observation timestamp, scheduled cadence slot, whether actual evaluation occurred, whether virtual evaluation occurred, comparable-opportunity flag, nearest matching actual/virtual session, timing gap in minutes/sessions.
- Define two validation modes: `STRICT_MATCHED_CADENCE` (compare decisions only where both actual and virtual evaluation opportunities existed within an allowed window) and `OPPORTUNITY_AWARE` (track virtual-only observations separately, do not count them as direct policy disagreements).
- Certification uses `STRICT_MATCHED_CADENCE` for action-agreement metrics by default.
- Classify virtual-only earlier interventions as `VIRTUAL_EARLIER_OPPORTUNITY`, not `POLICY_MISMATCH`. If actual later takes the same action, report timing difference separately; if actual takes a different action, distinguish cadence effect from policy disagreement.
- Missing actual snapshot → explicit exclusion/diagnostic state. Missing virtual snapshot → data-quality/censor state. No fabricated HOLD fills a missing observation.
- Material cadence-policy changes increment validation-policy version.

## Touches

- `covered_call_validation.py` (or equivalent management scheduler)
- DB schema (cadence slot, comparability columns)
- Learning Lab dashboard (comparable decision N, virtual-only N, actual-only N, cadence-divergence N, true policy-mismatch N)
- Tests

## Done when

- [ ] Actual and virtual evaluations at the same timestamp are classified as directly comparable
- [ ] A virtual evaluation with no actual counterpart within tolerance is classified `VIRTUAL_EARLIER_OPPORTUNITY`, not `POLICY_MISMATCH`
- [ ] One actual observation cannot pair to multiple virtual observations and vice versa
- [ ] Action-agreement denominator uses comparable observations only
- [ ] Cadence-only divergences have a separate N visible in the dashboard
- [ ] Missing actual snapshot produces an explicit exclusion record, not a silent HOLD
- [ ] Existing certification becomes invalid if cadence-comparability policy version changes
- [ ] Dashboard shows actual and virtual cadence distributions
