# Repair the Fixture Canary Assertions

- **ID:** 0655
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0652

## Problem

The existing `test_real_state_canary` fixture has four weak or incorrect assertions:

1. **Wrong Critic verdict string.** The fixture seeds `APPROVED` but production recognizes `APPROVE` / `APPROVE_WITH_CAUTION`. The supposedly Critic-approved recommendation lands in watch/non-approved behavior, not the approved-recommendation path it was meant to exercise.

2. **Incomplete intent exclusion check.** The fixture creates UNP=PENDING, RIVN=FILLED, STZ=REJECTED and only asserts that UNP appears. It does not assert that RIVN and STZ are absent — which is the important half of the contract (that execution lifecycle correctly excludes non-pending intents from `open_decisions`).

3. **Weak learning-sweep assertion.** `assert isinstance(ls, dict)` doesn't verify the seeded completed sweep was detected. Should assert that `learning_state["last_sweep"]` reflects the seeded `completed_at` timestamp.

4. **Macro staleness threshold is ambiguous.** The fixture uses exactly 72 hours (the stale threshold boundary). Due to timestamp rounding, this may or may not be stale. The assertion also does not verify that the advisory contract holds — it doesn't check that `freshness["macro_scores"]` is STALE and that this staleness appears in `context_warnings` but not in `brief_health_detail`.

## Proposed approach

Fix all four assertion gaps in `tests/test_portfolio_brief.py` (or wherever the canary lives):

1. **Fix Critic verdict:** change fixture insert from `APPROVED` to `APPROVE`. Add a second variant with `APPROVE_WITH_CAUTION` if the intent was to exercise both approval states.

2. **Assert intent exclusions:** add explicit assertions that RIVN (FILLED) does not appear in `open_decisions` and STZ (REJECTED) does not appear in `open_decisions`. The UNP (PENDING) assertion remains.

3. **Assert learning sweep detected:** replace `assert isinstance(ls, dict)` with `assert ls["last_sweep"] == expected_completed_at` (ISO string comparison) or equivalent, where `expected_completed_at` is the value seeded into the fixture.

4. **Make macro definitively stale:** change 72-hour offset to 96+ hours. Then assert:
   - `freshness["macro_scores"] == "STALE"` (or equivalent status)
   - `"macro_scores"` (or its label) appears in `context_warnings`
   - `"macro_scores"` staleness does not appear in `brief_health_detail` (advisory, not health-critical)

This last assertion is the actual proof that the ADVISORY tier contract from 0651 works end-to-end.

## Touches

- `tests/test_portfolio_brief.py` (or `tests/test_canary_real_state.py`) — the four fix points above; no new tables or functions needed

## Done when

- [ ] Fixture uses `APPROVE` (not `APPROVED`); Critic-approved recommendation exercises the approved path
- [ ] Asserts RIVN (FILLED) absent from `open_decisions`
- [ ] Asserts STZ (REJECTED) absent from `open_decisions`
- [ ] Learning-sweep assertion checks exact `last_sweep` timestamp, not just `isinstance(dict)`
- [ ] Macro fixture uses 96+ hour offset (definitively stale)
- [ ] Asserts `freshness["macro_scores"]` is STALE
- [ ] Asserts macro staleness appears in `context_warnings`
- [ ] Asserts macro staleness does NOT appear in `brief_health_detail`
