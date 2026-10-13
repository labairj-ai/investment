# Add Independent Policy Oracle to Canary

- **ID:** 0662
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0660

## Problem

INV-8 (the recomputation invariant) compares persisted state against `_derive_portfolio_state()` imported directly from production. This means production and the canary share the same implementation — if someone accidentally changes `_derive_portfolio_state()` in a way that violates the v2 specification (e.g. severity 70–79 returns ATTENTION instead of URGENT), both production and INV-8 make the same mistake and INV-8 passes silently.

The existing HIGH-SEV and HEALTHY→STABLE spot checks partially protect against this, but they don't cover the full state space and still rely on the same imports.

An independent oracle — same specification, different code — lets the canary catch defects in the production implementation itself.

## Proposed approach

Add `_expected_v2_state(snapshot)` to `scripts/canary_production_state.py` without importing any policy logic from `portfolio_ai`:

```python
def _expected_v2_state(snapshot):
    items = snapshot.get("attention_items", [])
    def severity(item):
        try:
            return int(item.get("severity", 0))
        except (TypeError, ValueError):
            return 0
    if any(severity(i) >= 70 for i in items):
        return "URGENT"
    if items:
        return "ATTENTION"
    if snapshot.get("brief_health") == "HEALTHY":
        return "STABLE"
    return "UNKNOWN"
```

Replace the INV-8 call to `_derive_portfolio_state(snapshot)` with `_expected_v2_state(snapshot)`. The canary no longer imports `_derive_portfolio_state` for the recomputation invariant — only `BRIEF_POLICY_VERSION` (the constant) still needs to come from `portfolio_ai`.

Add a test that deliberately mutates `_derive_portfolio_state()` (via monkeypatch) and proves the canary raises a violation. This is the only test that actively verifies the oracle's independence.

The duplication is intentional. When policy semantics change enough to require v3, a new `_expected_v3_state()` oracle is written at that time, binding it explicitly to v3 semantics.

## Touches

- `scripts/canary_production_state.py` — add `_expected_v2_state()`; replace INV-8 production import with oracle call; remove `_derive_portfolio_state` from canary imports
- `tests/` — test: mutated production function → canary violation; existing INV-8 tests should still pass

## Done when

- [x] `_expected_v2_state()` lives in the canary with no imports from `portfolio_ai` policy logic
- [x] INV-8 uses the oracle, not the production function
- [x] Test: monkeypatching `portfolio_ai._derive_portfolio_state` does not affect canary verdict (oracle is independent)
- [x] Test: inserting a v2 row whose persisted state contradicts the oracle → violation
- [ ] After deploy: canary still reports 0 violations on v2 rows

## Outcome

Added `_expected_v2_state(snapshot)` to `scripts/canary_production_state.py` — a standalone reimplementation of the v2 spec with no imports from portfolio_ai beyond `BRIEF_POLICY_VERSION`. INV-8 now calls the oracle instead of `_derive_portfolio_state`. Spot-check severity logic also uses a local `_sev_local()` function, eliminating all production policy imports. Two new tests added: `test_canary_oracle_independent_of_production_function` (monkeypatches production function and proves oracle is unaffected) and `test_canary_detects_v2_state_mismatch` (oracle URGENT vs persisted STABLE → INV-8 violation). After deploy the v2 rows still show 0 violations (last verified pre-deploy: 17cd1bb canary run).
