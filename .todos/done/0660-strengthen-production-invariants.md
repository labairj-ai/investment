# Strengthen Production Canary Invariants

- **ID:** 0660
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0658, 0659

## Problem

The current production canary checks several prohibited combinations (attention + STABLE) but cannot catch violations in the other direction: high-severity attention that was incorrectly ATTENTION instead of URGENT, medium attention that landed as UNKNOWN, or a healthy no-attention brief that was incorrectly URGENT. The current "0 violations from current code" result is encouraging but does not prove the 0658 invariant holds — it only proves none of the old specific violations were introduced.

The correct invariant for current-policy (`brief_policy_version == "v2"`) rows is:

```python
expected = _derive_portfolio_state(brief_snapshot)
actual = briefing_output["portfolio_state"]
assert actual == expected
```

This one check subsumes all the combination checks and catches any deviation from the pure function.

## Proposed approach

In `scripts/canary_production_state.py`, for rows where `brief_policy_version == "v2"`:

- Parse `brief_snapshot_json` from `portfolio_brief_provenance`
- Call `_derive_portfolio_state(snapshot)` (import from `portfolio_ai`)
- Compare to `briefing_output_json["portfolio_state"]`
- If they differ: violation

This is the **recomputation invariant** — independently recompute the expected state from stored evidence and require exact equality with what was persisted.

Also add:
- **High-severity → URGENT check:** for v2 rows, if `brief_snapshot_json.attention_items` contains any item with `severity >= 70`, assert `portfolio_state == "URGENT"`.
- **No-attention + HEALTHY → STABLE check:** for v2 rows, if `attention_items == []` and `brief_health == "HEALTHY"`, assert `portfolio_state == "STABLE"` (not UNKNOWN, URGENT, or ATTENTION).
- **No-attention + HEALTHY → not URGENT check:** equivalent ceiling check.

Remove the old combination-based checks that are now subsumed by the recomputation invariant, or keep them as redundant belt-and-suspenders only if they're still informative.

## Touches

- `scripts/canary_production_state.py` — import `_derive_portfolio_state` from `portfolio_ai`; add recomputation invariant for v2 rows; add high-severity and no-attention+healthy spot checks
- `portfolio_ai.py` — `_derive_portfolio_state()` must be importable (if extracted as standalone function in 0658, it already is)
- `tests/` — test the canary script logic directly: a v2 provenance row with STABLE but non-empty attention → violation; a v2 row where computed state matches stored state → pass

## Done when

- [ ] Canary recomputes `_derive_portfolio_state(brief_snapshot)` for every v2 row and compares to persisted `portfolio_state`
- [ ] Any mismatch between recomputed and persisted state → violation
- [ ] High-severity attention + non-URGENT persisted state → violation
- [ ] No-attention + HEALTHY + non-STABLE persisted state → violation
- [ ] `_derive_portfolio_state` is importable from `portfolio_ai`
- [ ] After deploy: canary runs clean (0 violations on v2 rows, legacy rows classified as legacy)
