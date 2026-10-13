# Snapshot Integrity: Full Equality and Hash

- **ID:** 0664
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0661

## Problem

The persistence chain test currently compares only selected fields (`portfolio_state`) between `portfolio_brief_snapshots.snapshot_json` and `portfolio_brief_provenance.brief_snapshot_json`. But `portfolio_state` is a derived output field that may not be a normal member of the raw state snapshot — so the assertion can trivially pass as `None == None` without proving anything.

Additionally, there is no tamper-evident link between the two records. A future bug where one table receives a different snapshot than the other would not be detected until a symptom surfaced downstream.

## Proposed approach

**Immediate test fix:**
Replace the field-by-field comparison with a full canonical equality check:

```python
def _canonical(obj):
    # stable JSON: sorted keys, no whitespace
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))

assert _canonical(snap_from_snapshots) == _canonical(snap_from_provenance)
```

If there are legitimately volatile fields (e.g. a `generated_at` timestamp that varies), canonicalize by removing them explicitly before comparison. Document which fields are excluded and why.

**Longer-term (optional for this todo):**
Persist `brief_snapshot_hash = SHA256(_canonical(brief_state))` in both `portfolio_brief_snapshots` and `portfolio_brief_provenance` at write time. The canary then checks:

```python
assert snap_row["snapshot_hash"] == prov_row["brief_snapshot_hash"]
```

This means snapshot integrity is checkable from the DB alone without deserializing JSON, and any divergence between the two records is immediately detectable.

The hash approach makes provenance verifiable from the outside: if a third party has the `brief_state` JSON they can independently verify `SHA256(canonical_json) == stored_hash`.

## Touches

- `tests/test_portfolio_brief.py` — replace field-level snapshot comparison with full canonical equality; document excluded volatile fields
- `portfolio_ai.py` — (optional) compute and persist `brief_snapshot_hash` in both tables in `create_portfolio_brief()`
- `scripts/canary_production_state.py` — (optional) add hash-equality invariant for v2 rows that have hash columns

## Done when

- [x] Persistence chain test compares full canonical snapshot equality (not just selected fields)
- [x] Any volatile fields excluded from comparison are explicitly named in a comment
- [x] Test fails if `portfolio_brief_snapshots` and `portfolio_brief_provenance` receive different snapshots for the same `brief_id`
- [ ] (Optional) `brief_snapshot_hash` persisted in both tables; canary checks equality

## Outcome

Replaced the two field-level assertions (`attention_items ==` and `portfolio_state ==`) in `test_persistence_chain_policy_corrects_llm_stable` with a single `_canonical(snap_from_snapshots) == _canonical(snap_from_provenance)` comparison using `json.dumps(obj, sort_keys=True, separators=(",", ":"))`. No volatile fields needed exclusion since `brief_state` doesn't contain `generated_at` (that's in `briefing_output`). Both snapshot tables receive `json.dumps(brief_state)` from the same object in one SAVEPOINT, so they must be byte-identical. The comment documents this. Hash column deferred (optional path).
