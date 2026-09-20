# Extract Pure Strategy Config into Dedicated Module

- **ID:** 0449
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0446

## Problem

`scripts/freeze_baseline.py` imports `agents/opportunity_agent` solely to read
`COMPOSITE_WEIGHTS` and `MIN_COMPOSITE`, but importing that module also executes
agent registration and loads a substantial amount of application code — more
coupling than a config-reading utility should carry. `book_simulator._STARTING_CASH`
is now imported by an external caller despite being a private-convention name, making
the "private" naming misleading and the public contract implicit.

## Proposed approach

- Create `agents/opportunity_config.py` as a pure, side-effect-free module:
  ```python
  COMPOSITE_WEIGHTS: dict[str, float] = {"Q": 0.30, "V": 0.25, "PF": 0.20, "C": 0.15, "EC": 0.10}
  MIN_COMPOSITE: int = 45
  VIRTUAL_BOOK_STARTING_CASH: float = 100_000.0
  ```
- Update `agents/opportunity_agent.py` to import `COMPOSITE_WEIGHTS` and
  `MIN_COMPOSITE` from `opportunity_config` and remove the locally-defined
  copies; `_composite()` continues to consume `COMPOSITE_WEIGHTS` (per 0446).
- Update `agents/learning/book_simulator.py` to import `VIRTUAL_BOOK_STARTING_CASH`
  from `opportunity_config` and replace `_STARTING_CASH` usages.
- Update `scripts/freeze_baseline.py` to import from `opportunity_config` instead
  of `opportunity_agent`.
- Update any tests that currently patch `opportunity_agent.COMPOSITE_WEIGHTS` or
  `book_simulator._STARTING_CASH` to patch `opportunity_config.*` instead.
- Question: should `opportunity_config.py` live in `agents/` or at the project
  root alongside `strategy_config.py`? Probably `agents/` to stay co-located with
  the code it configures.

## Touches

- `agents/opportunity_config.py` (new)
- `agents/opportunity_agent.py`
- `agents/learning/book_simulator.py`
- `scripts/freeze_baseline.py`
- `tests/` (any tests patching the old locations)

## Done when

- [ ] `agents/opportunity_config.py` exists as a pure module with no imports beyond the stdlib
- [ ] `opportunity_agent.py` and `book_simulator.py` import their constants from `opportunity_config`
- [ ] `freeze_baseline.py` imports only from `opportunity_config`, not from `opportunity_agent`
- [ ] No reference to `_STARTING_CASH` remains outside `opportunity_config.py`; `VIRTUAL_BOOK_STARTING_CASH` is the public name
- [ ] All existing tests pass after the rename
