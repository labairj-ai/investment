# Tag Decision Episodes with Validation Status and Acceptance Contract

- **ID:** 0497
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0494

## Problem

0494 is already capturing macro snapshots into Decision Episodes, but the live 20-repeat acceptance (0498) has not yet run. Episodes captured now are pre-acceptance: they may be useful for engineering diagnostics but should not be mixed with post-acceptance episodes in formal attribution. Without a validation status tag, early experimental data silently gets mixed with later validated evidence.

## Proposed approach

Add three fields to the `macro_snapshot` JSON blob in each `decision_episodes` row:

- `macro_validation_status`: `"PRE_ACCEPTANCE"` until the first live acceptance PASS; `"ACCEPTED"` after
- `macro_validation_contract`: null until acceptance; then e.g. `"macro_validation_v1"`
- `macro_validation_record_id`: null until acceptance; then the timestamp/ID of the acceptance record from 0498

At acceptance time (0498 PASS), write a `macro_acceptance_state` row to a new small table (or a JSON config file):
```
{"contract": "macro_validation_v1", "accepted_at": "...", "record_id": "...", "commit_sha": "..."}
```

Episode capture (`_build_macro_snapshot`) reads this state at runtime:
- If acceptance record exists → status = "ACCEPTED", populate contract + record_id
- Otherwise → status = "PRE_ACCEPTANCE"

`macro_attribution.py` should by default only include ACCEPTED episodes in formal analysis; add `--include-pre-acceptance` flag for diagnostic use.

## Touches

- `portfolio_ai.py` — `_build_macro_snapshot()`, new `macro_acceptance_state` table
- `scripts/macro_attribution.py` — default filter on `macro_validation_status = "ACCEPTED"`

## Done when

- [ ] All new episodes carry `macro_validation_status` in their macro_snapshot
- [ ] Episodes before live acceptance are tagged `PRE_ACCEPTANCE`
- [ ] After 0498 PASS, new episodes tagged `ACCEPTED` with contract + record_id
- [ ] Attribution script defaults to ACCEPTED-only; `--include-pre-acceptance` available for diagnostics
