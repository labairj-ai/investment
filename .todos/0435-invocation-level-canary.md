# Anchor Canary on Latest Attempt, Audit All Models in OH Run

- **ID:** 0435
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0434

## Problem

`canary_audit.sh` currently anchors on `status='COMPLETED' ORDER BY id DESC LIMIT 1`. If a sweep runs at 10:00 (COMPLETED) and a second runs at 12:00 (FAILED), the 12:01 canary selects the earlier successful sweep and passes — completely missing the current failure. Additionally, one OH invocation can touch multiple learning models (OBSERVE, PAPER_ACTIVE, SUSPENDED) simultaneously; auditing one ledger row is not enough to confirm the full invocation was healthy.

## Proposed approach

- **Anchor change:** Remove the `status='COMPLETED'` filter from the anchor query. Select the latest ledger row unconditionally (`ORDER BY id DESC LIMIT 1`). Then require that row to be COMPLETED + scored==expected; fail immediately if it is not.
- **Full-invocation audit:** From the anchor row's `agent_run_id` and `cohort_id`, fetch all `learning_sweep_runs` rows sharing that `agent_run_id`. For each model in that invocation:
  - status must be COMPLETED
  - scored_candidates must equal expected_candidates
  - winner invariants (exactly one would_select=1, one base_would_select=1)
  - episode lineage (every obs episode → decision_episodes.run_id == anchor agent_run_id)
  - variant parity for PAPER_ACTIVE model(s) only
- Remove the SKIP paths for missing agent_run_id — post-0434, agent_run_id is always set; a missing value is a failure, not a skip.
- Question: how to handle invocations with no PAPER_ACTIVE model (variant parity check not applicable)? Skip gracefully with a note rather than failing.

## Touches

- `scripts/canary_audit.sh` — complete rewrite of anchor + assertion logic

## Done when

- [ ] Canary anchor uses latest ledger row regardless of status; fails if not COMPLETED+exact
- [ ] Canary fetches all ledger rows for the anchored agent_run_id and checks each model
- [ ] A FAILED sweep in the most recent invocation causes canary exit 1
- [ ] Winner and lineage checks run per-model for the full invocation
- [ ] Canary correctly handles 1-model and N-model OH runs
