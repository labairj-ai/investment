# Refactor evaluate_cc_management_state() to Accept Pure ManagementPolicyContext

- **ID:** 0162
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0157, 0158, 0159, 0160, 0161

## Problem

`evaluate_cc_management_state()` and `_check_assignment_eligible()` currently reach outward into the database for thesis records, tax lots, and portfolio history. This mixes financial-policy logic with data-access concerns and makes the canonical management engine hard to test deterministically — a unit test must mock `agent_db`, `strategy_config`, and DB connections.

## Proposed approach

Define a `ManagementPolicyContext` dataclass that the caller (the agent, not the rule engine) pre-assembles from all live sources:

```python
@dataclass
class ManagementPolicyContext:
    # Option position
    current_price: float
    strike: float
    dte: int
    delta: float | None
    remaining_extrinsic: float | None
    pct_captured: float | None
    has_avoid: bool
    risk_events: list
    contracts: int

    # Assignment policy (from cc_policy)
    assignment_price_floor: float | None
    assignment_policy: dict

    # Live portfolio state (from AgentContext.snapshot)
    current_weight_pct: float | None

    # Thesis state (pre-fetched by agent)
    conviction: int | None
    thesis_health: float | None          # None = unavailable
    max_position_pct: float | None

    # Tax friction (pre-computed by agent)
    assignment_tax_friction: float       # avoidable dollars; 0 = no friction
    tax_friction_reason: str
```

`evaluate_cc_management_state(ctx: ManagementPolicyContext) -> tuple[str, str]` becomes a pure function with zero DB calls. The agent assembles the context object; the engine makes the decision.

The agent (`_analyze_roll()`) pre-fetches thesis data, runs `_lot_tax_friction()`, reads `snapshot.holdings`, and bundles everything into a `ManagementPolicyContext` before calling the engine.

This is a cleanup that lands after all the individual gate fixes (0157–0161) are done, since each fix clarifies exactly which fields the context needs.

## Touches

- `covered_call_rec.py` — new `ManagementPolicyContext` dataclass; `evaluate_cc_management_state()` signature becomes `(ctx: ManagementPolicyContext)`; `_check_assignment_eligible()` refactored to accept context fields (no DB calls)
- `agents/covered_call_agent.py` — `_analyze_roll()`: assemble `ManagementPolicyContext` before calling engine
- `tests/test_covered_call_agent.py` — all determinism tests can now use plain context objects, no DB mocks

## Done when

- [ ] `ManagementPolicyContext` dataclass defined in `covered_call_rec.py`
- [ ] `evaluate_cc_management_state()` accepts a single context object with no internal DB calls
- [ ] `_check_assignment_eligible()` reads only from context fields
- [ ] `_analyze_roll()` assembles context from snapshot + DB pre-fetch before calling engine
- [ ] All existing management tests pass; new tests use context objects without mocking DB
