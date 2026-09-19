# Document or Extract _composite_6() as Explicit Separate Contract

- **ID:** 0453
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0449

## Problem

`_composite_6()` in `agents/opportunity_agent.py` hard-codes its own
25/20/20/15/10/10 weighting for a 6-component candidate comparison score. Now that
the main 5-component weights live in `opportunity_config.COMPOSITE_WEIGHTS`, a future
maintainer will reasonably assume `_composite_6()` is another accidental duplication
rather than an intentional separate contract. The ambiguity matters for experiment
integrity: if `COMPOSITE_WEIGHTS` is ever updated for the learning experiment, it
must be clear whether `_composite_6()` should change with it or stay fixed.

## Proposed approach

Decide first, then implement one of two paths:

- **If independent (likely):** add a comment above `_composite_6()` explicitly
  stating these weights are for candidate comparison only and are intentionally
  decoupled from `COMPOSITE_WEIGHTS`. Add a test that asserts the two weight sets
  differ (so a future accidental merge is caught). Optionally name the constants
  `_COMPARISON_WEIGHTS` locally or in `opportunity_config` for symmetry.

- **If it should track the experiment contract:** extract into
  `opportunity_config.COMPARISON_WEIGHTS` and update `_composite_6()` to consume it,
  exactly as was done for `_composite()` in 0446.

The key deliverable is that the intent is unambiguous to a reader who has no context
from this conversation.

## Touches

- `agents/opportunity_agent.py`
- `agents/opportunity_config.py` (if extracting weights)
- `tests/` (new assertion about weight independence or config coverage)

## Done when

- [ ] A decision is made and recorded (comment, config entry, or both)
- [ ] A test enforces the chosen contract (either independence or shared source)
- [ ] No reader can mistake `_composite_6()` weights for an accidental duplicate of `COMPOSITE_WEIGHTS`
