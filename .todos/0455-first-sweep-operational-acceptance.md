# Validate First Live Learning Sweep and Freeze Architecture

- **ID:** 0455
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0454

## Problem

`config/experiment_integrity_record.json` confirms 1132 tests passing and all
provenance architecture is in place, but no live Opportunity Hunter run has yet
produced a learning ledger row. Architecture validation is complete; live
learning-pipeline validation is pending. Until the first real sweep runs cleanly
end-to-end, there is no proof that the DB wiring, sweep counts, observation
recording, and canary checks all hold in production. This is the final gate before
the architecture is frozen and the project shifts to accumulating evidence.

## Proposed approach

When the first OH run creates a `learning_sweep_runs` row, perform the following
checks manually (or via a small capture script):

1. Verify the newest `learning_sweep_runs` row has `status=COMPLETED` and
   `expected_candidates == scored_candidates`.
2. Run `scripts/canary_audit.sh` against the live DB — must exit 0.
3. Run `python check_integrity.py` — must pass.
4. Confirm exactly one base winner and one challenger winner for the cohort.
5. Confirm all `model_observations` rows for the cohort map to the same
   `agent_run_id` as the sweep row.
6. If a PAPER_ACTIVE model is set: confirm the paper variant's
   `challenger_episode_id` equals the shadow-selected challenger episode.

Save results as an append-only `config/experiment_canary_001.json`:
```json
{
  "source_commit_sha": "...",
  "agent_run_id": "...",
  "cohort_id": "...",
  "model_version": "...",
  "phase": "OBSERVE",
  "expected_candidates": N,
  "scored_candidates": N,
  "canary_result": "PASS",
  "integrity_check_result": "PASS",
  "recorded_at": "..."
}
```

If all checks pass: **freeze the architecture**. No further changes to
`COMPOSITE_WEIGHTS`, `MIN_COMPOSITE`, candidate eligibility logic, holding
horizon definition, or model contract while observations accumulate.

## Touches

- `config/experiment_canary_001.json` (new — created when sweep occurs)
- `scripts/canary_audit.sh` (run only, no changes)
- `check_integrity.py` (run only, no changes)

## Done when

- [ ] First `learning_sweep_runs` row is COMPLETED with matching candidate counts
- [ ] `canary_audit.sh` passes against the live DB
- [ ] `check_integrity.py` passes
- [ ] Base winner and challenger winner confirmed for the cohort
- [ ] All observations map to the correct `agent_run_id`
- [ ] `config/experiment_canary_001.json` committed as an append-only record
- [ ] Architecture frozen — no scoring/contract changes until 20–30 mature cohorts exist
