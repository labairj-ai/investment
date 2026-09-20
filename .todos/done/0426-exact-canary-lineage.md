# Exact Canary Lineage

- **ID:** 0426
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0424, 0425

## Problem

`scripts/canary_audit.sh` currently derives its audit anchor by independently querying:
- latest `decision_episodes.run_id`
- latest `model_observations.decision_cohort_id`

These are verified separately without proving they came from the same OH invocation. Under
normal operation they will, but an audit tool for an integrity system should not rely on timing
assumptions — that's exactly the class of assumption the sweep ledger was designed to eliminate.

## Proposed approach

- Start the canary from one completed `learning_sweep_runs` row (most recent COMPLETED status).
- Extract `agent_run_id`, `cohort_id`, `model_version`, `phase`, `expected_candidates`,
  `scored_candidates`, `base_recommendation_eligible` from that single row.
- Derive all subsequent assertions from those three IDs:
  - `decision_episodes` count for `agent_run_id`
  - `model_observations` count for `(model_version, decision_cohort_id)`
  - `would_select=1` count for `(model_version, decision_cohort_id)`
  - `base_would_select=1` count for `(model_version, decision_cohort_id)`
  - `decision_variants.challenger_episode_id` matches the `would_select` observation's episode
- This makes the canary a single-source audit: one ledger row determines the entire check scope.
- Requires 0424 (agent_run_id populated) and 0425 (scored_candidates is authoritative).

## Touches

- `scripts/canary_audit.sh` — rewrite anchor selection to start from ledger row

## Done when

- [ ] Canary selects one COMPLETED ledger row as its audit anchor
- [ ] All assertions derived from `agent_run_id`, `cohort_id`, `model_version` from that row
- [ ] No independent "latest" queries that could produce a cross-run mismatch
- [ ] Script exit 0 / 1 behavior preserved
