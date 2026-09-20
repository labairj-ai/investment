# Make _composite() Consume COMPOSITE_WEIGHTS

- **ID:** 0446
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0445

## Problem

`_composite()` in `agents/opportunity_agent.py` still hard-codes literal weights
(`0.30 * q + 0.25 * v + ...`) rather than reading from the exported
`COMPOSITE_WEIGHTS` dict, so the dict and the function are two independent sources
of truth. Changing `COMPOSITE_WEIGHTS["Q"]` changes what `freeze_baseline.py`
records but does not change what the Opportunity Hunter actually scores. The
`_MIN_COMPOSITE` / `MIN_COMPOSITE` pair has the same problem: both names exist, the
gate references the private one, so `MIN_COMPOSITE` is only a cosmetic re-export.

## Proposed approach

- Refactor `_composite()` to compute from `COMPOSITE_WEIGHTS`:
  ```python
  def _composite(q, v, pf, c, ec):
      components = {"Q": q, "V": v, "PF": pf, "C": c, "EC": ec}
      return round(sum(COMPOSITE_WEIGHTS[k] * components[k] for k in COMPOSITE_WEIGHTS))
  ```
- Collapse the dual threshold: replace `_MIN_COMPOSITE = 45 / MIN_COMPOSITE = _MIN_COMPOSITE`
  with a single `MIN_COMPOSITE = 45`, and update all internal references (the gate
  check, threshold log messages) to use `MIN_COMPOSITE` directly.
- Add a test (in `tests/test_calibration.py` or a dedicated opportunity-agent test
  file) that temporarily patches `COMPOSITE_WEIGHTS` and asserts that `_composite()`
  returns the expected changed value. This prevents the regression from reappearing.
- Verify `_composite_6()` (the 6-component variant) — decide whether it should also
  read from a second config dict or stay as-is (document the choice).

## Touches

- `agents/opportunity_agent.py`
- `tests/test_calibration.py` (or new `tests/test_opportunity_agent.py`)

## Done when

- [ ] `_composite()` computes its result entirely from `COMPOSITE_WEIGHTS` with no separate literal weights
- [ ] A single constant `MIN_COMPOSITE` is used by both the gate logic and the public export (no `_MIN_COMPOSITE` alias needed)
- [ ] A test patches `COMPOSITE_WEIGHTS` and confirms `_composite()` output changes accordingly
- [ ] All existing tests continue to pass
