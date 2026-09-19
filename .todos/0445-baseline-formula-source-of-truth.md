# Derive Baseline Formula from Authoritative Source

- **ID:** 0445
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0442

## Problem

`scripts/freeze_baseline.py` hard-codes the Opportunity Hunter composite formula
weights (`0.30*Q + 0.25*V + 0.20*PF + 0.15*C + 0.10*EC`) and the minimum composite
threshold (`45`) as string and dict literals rather than importing them from
`agents/opportunity_agent.py`. If the formula or threshold is updated in the actual
scoring code, `freeze_baseline.py` will silently record the wrong values, making the
frozen snapshot an unreliable record of what was actually running during the experiment.

## Proposed approach

- Export the weights and threshold from `agents/opportunity_agent.py` as named module-
  level constants (e.g. `COMPOSITE_WEIGHTS` dict and `MIN_COMPOSITE` is already
  `_MIN_COMPOSITE`; make them importable).
- Update `_load_formula_params()` in `freeze_baseline.py` to import those constants
  directly rather than duplicating them.
- Derive the human-readable formula string programmatically from the weights dict
  so it stays in sync automatically.
- Regenerate `config/experiment_baseline.json` after the fix and recommit, so the
  committed snapshot was produced by the corrected script.

## Touches

- `agents/opportunity_agent.py` (expose `_MIN_COMPOSITE` and weights as importable constants)
- `scripts/freeze_baseline.py` (import instead of hard-code)
- `config/experiment_baseline.json` (regenerated)

## Done when

- [ ] `freeze_baseline.py` imports composite weights and threshold from `opportunity_agent.py` rather than defining them locally
- [ ] Changing the formula in `opportunity_agent.py` automatically changes what `freeze_baseline.py` would record on the next freeze
- [ ] `config/experiment_baseline.json` is regenerated from the corrected script and recommitted
