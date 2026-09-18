# Complete Canary Lineage: Episode Count + Row-Level Run Proof

- **ID:** 0434
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0426

## Problem

`canary_audit.sh` currently verifies only that *some* `decision_episodes` rows exist for the ledger's `agent_run_id` — not that the count matches `expected_candidates`, and not that every `model_observations` row in the anchored cohort belongs to an episode from that specific run. A sweep that partially matched a different run could pass the canary. Additionally, `agent_run_id` is still optional in `score_for_observe()`; a caller that omits it silently creates an unverifiable ledger row.

## Proposed approach

- **Canary assertion 1 (count):** `COUNT(*) FROM decision_episodes WHERE run_id = AGENT_RUN_ID` must equal `EXP_CANDS`. Add this as a new numbered check in `canary_audit.sh`.
- **Canary assertion 2 (row-level lineage):** Every `model_observations.episode_id` in the anchored cohort must join to a `decision_episodes` row with `run_id = AGENT_RUN_ID`. Report count of non-joining rows; fail if > 0.
- **Make `agent_run_id` mandatory:** Remove `| None = None` default from `score_for_observe()` signature; callers must supply it (same pattern as `cohort_id` after 0406). Update `opportunity_agent.py` call site (already passes it); add a guard that raises `ValueError` if `None` is passed.
- Update the canary SKIP path (currently triggered when `AGENT_RUN_ID` is empty) to become a hard FAIL for post-rollout sweeps.

## Touches

- `scripts/canary_audit.sh` — two new assertions (episode count, row-level lineage)
- `agents/learning/challenger.py` — remove `agent_run_id` default; add None guard
- `agents/opportunity_agent.py` — verify call site still passes `agent_run_id`
- `tests/test_calibration.py` — test that omitting `agent_run_id` raises; canary structure tests

## Done when

- [ ] `canary_audit.sh` asserts `decision_episodes` count == `expected_candidates` for the anchored `agent_run_id`
- [ ] `canary_audit.sh` asserts every cohort observation's episode_id joins to the anchored `agent_run_id`
- [ ] `score_for_observe()` raises `ValueError` when `agent_run_id` is `None`
- [ ] Tests confirm both new canary assertions and the mandatory-arg guard
